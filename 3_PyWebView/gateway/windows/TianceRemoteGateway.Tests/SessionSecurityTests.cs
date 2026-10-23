using System.Net;
using Microsoft.AspNetCore.Http;
using Xunit;

namespace Tiance.RemoteGateway.Tests;

public sealed class SessionSecurityTests
{
    private sealed class Clock : TimeProvider
    {
        private DateTimeOffset _now = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => _now;
        public void Advance(TimeSpan by) => _now += by;
    }

    [Fact]
    public void HeartbeatsAndReadsDoNotExtendIdleTimeout()
    {
        var clock = new Clock();
        using var store = new SessionStore(clock);
        var token = store.Create();
        var session = store.Get(token)!;
        for (var i = 0; i < 120; i++)
        {
            Assert.True(store.Touch(token, "page", false));
            Assert.True(store.IsValid(token));
            clock.Advance(TimeSpan.FromSeconds(30));
        }
        store.Sweep();
        Assert.False(store.IsValid(token));
        Assert.True(session.Revoked.IsCancellationRequested);
        Assert.False(store.Touch(token, "page", true));
    }

    [Fact]
    public void ActivityExtendsIdleButCannotExtendAbsoluteExpiry()
    {
        var clock = new Clock();
        using var store = new SessionStore(clock);
        var token = store.Create();
        for (var i = 0; i < 24 * 120; i++)
        {
            Assert.True(store.Touch(token, "page", true));
            clock.Advance(TimeSpan.FromSeconds(30));
        }
        Assert.False(store.Touch(token, "page", true));
    }

    [Fact]
    public void ClosingOneTabDoesNotRevokeOtherTabAndRefreshCanReconnect()
    {
        var clock = new Clock();
        using var store = new SessionStore(clock);
        var token = store.Create();
        store.Touch(token, "a", false);
        store.Touch(token, "b", false);
        store.Leave(token, "a");
        Assert.False(store.Touch(token, "a", false)); // Late heartbeat cannot resurrect a closed page.
        clock.Advance(TimeSpan.FromSeconds(20));
        Assert.True(store.Touch(token, "b", false));
        store.Leave(token, "b");
        clock.Advance(TimeSpan.FromSeconds(10));
        Assert.True(store.Touch(token, "refresh", false));
        store.Leave(token, "refresh");
        clock.Advance(SessionStore.ReconnectGrace);
        Assert.False(store.IsValid(token));
    }

    [Fact]
    public void LostPageAndRevocationCancelAllAttachedTransports()
    {
        var clock = new Clock();
        using var store = new SessionStore(clock);
        var lost = store.Create();
        var session = store.Get(lost)!;
        store.Touch(lost, "page", false);
        clock.Advance(SessionStore.PresenceTimeout);
        store.Sweep();
        Assert.True(session.Revoked.IsCancellationRequested);
        var token = store.Create();
        var active = store.Get(token)!;
        var cancelled = 0;
        using var http = active.Revoked.Register(() => cancelled++);
        using var ws = active.Revoked.Register(() => cancelled++);
        var anonymous = store.Anonymous;
        store.Clear();
        Assert.Equal(2, cancelled);
        Assert.False(store.IsValid(token));
        Assert.True(anonymous.Revoked.IsCancellationRequested);
        Assert.False(store.Desktop.Revoked.IsCancellationRequested);
    }

    [Fact]
    public async Task LoopbackAndForgedForwardingHeadersDoNotGrantDesktopIdentity()
    {
        var directory = Path.Combine(Path.GetTempPath(), "tiance-gateway-test-" + Guid.NewGuid());
        Directory.CreateDirectory(directory);
        try
        {
            var settings = new GatewaySettingsStore(directory);
            settings.Update(s => s with { PasswordHash = "set", PasswordSalt = "set", LocalBypassEnabled = true });
            using var sessions = new SessionStore();
            var options = new GatewayOptions("127.0.0.1", 18000, "http://127.0.0.1:18200/", directory, true, "");
            var secret = new string('a', 64);
            var security = new GatewaySecurity(options, settings, sessions, new GatewayBootstrap(secret, new string('b', 64)));
            DefaultHttpContext Context()
            {
                var context = new DefaultHttpContext();
                context.Connection.RemoteIpAddress = IPAddress.Loopback;
                context.Request.Host = new HostString("127.0.0.1", 18000);
                context.Request.Scheme = "http";
                context.Request.Path = "/api/private";
                context.Response.Body = new MemoryStream();
                return context;
            }
            var forwarded = Context();
            forwarded.Request.Headers["X-Forwarded-For"] = "203.0.113.4";
            await security.Invoke(forwarded, _ => throw new Exception("Bypassed authentication"));
            Assert.Equal(401, forwarded.Response.StatusCode);
            var native = Context();
            native.Request.Headers.Cookie = SessionStore.DesktopCookieName + "=" + secret;
            Assert.True(security.Authorized(native));
            native.Connection.RemoteIpAddress = IPAddress.Parse("192.0.2.1");
            Assert.False(security.Authorized(native));
            var hostile = Context();
            hostile.Request.Headers.Cookie = SessionStore.DesktopCookieName + "=" + secret;
            hostile.Request.Headers.Origin = "https://untrusted.invalid";
            await security.Invoke(hostile, _ => throw new Exception("Accepted foreign origin"));
            Assert.Equal(403, hostile.Response.StatusCode);
            var navigation = Context();
            navigation.Request.Path = "/app/";
            navigation.Request.Method = "GET";
            navigation.Request.Headers["Sec-Fetch-Site"] = "cross-site";
            var served = false;
            await security.Invoke(navigation, _ => { served = true; return Task.CompletedTask; });
            Assert.True(served);
            settings.Update(s => s with { LocalBypassEnabled = false });
            native.Connection.RemoteIpAddress = IPAddress.Loopback;
            Assert.False(security.Authorized(native));
        }
        finally { Directory.Delete(directory, true); }
    }
}
