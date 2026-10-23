using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AspNetCore.Http;

namespace Tiance.RemoteGateway;

internal sealed record GatewayBootstrap(string DesktopToken, string BackendToken)
{
    public const string InternalHeader = "X-Tiance-Gateway-Token";
    public static GatewayBootstrap Read()
    {
        if (!Console.IsInputRedirected) throw new InvalidOperationException("Gateway must be started by the desktop host.");
        var line = Console.In.ReadLineAsync().WaitAsync(TimeSpan.FromSeconds(5)).GetAwaiter().GetResult();
        var bootstrap = JsonSerializer.Deserialize<GatewayBootstrap>(line ?? "");
        if (bootstrap is null || !ValidToken(bootstrap.DesktopToken) || !ValidToken(bootstrap.BackendToken))
            throw new InvalidOperationException("Invalid gateway bootstrap credentials.");
        return bootstrap;
    }
    private static bool ValidToken(string? token) => token?.Length == 64 && token.All(Uri.IsHexDigit);
}

internal sealed class GatewaySecurity(GatewayOptions options, GatewaySettingsStore settings, SessionStore sessions, GatewayBootstrap bootstrap)
{
    private readonly HashSet<string> _hosts = (Environment.GetEnvironmentVariable("TIANCE_GATEWAY_ALLOWED_HOSTS") ?? "")
        .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries).ToHashSet(StringComparer.OrdinalIgnoreCase);

    public bool IsDesktop(HttpContext context)
    {
        var token = context.Request.Cookies[SessionStore.DesktopCookieName];
        var host = context.Request.Host.Host.Trim('[', ']');
        return context.Connection.RemoteIpAddress is { } address && IPAddress.IsLoopback(address)
            && (host.Equals("localhost", StringComparison.OrdinalIgnoreCase) || (IPAddress.TryParse(host, out var ip) && IPAddress.IsLoopback(ip)))
            && token?.Length == 64
            && CryptographicOperations.FixedTimeEquals(Encoding.UTF8.GetBytes(token), Encoding.UTF8.GetBytes(bootstrap.DesktopToken));
    }

    public AccessSession? Session(HttpContext context)
    {
        var desktop = sessions.Desktop;
        if (settings.Read().LocalBypassEnabled && IsDesktop(context)) return desktop;
        return sessions.Get(context.Request.Cookies[SessionStore.CookieName]);
    }

    public bool Authorized(HttpContext context) => !settings.Read().HasPassword || Session(context) is not null;

    public async Task Invoke(HttpContext context, RequestDelegate next)
    {
        var host = context.Request.Host.Host.Trim('[', ']');
        if (!(host.Equals("localhost", StringComparison.OrdinalIgnoreCase) || IPAddress.TryParse(host, out _) || _hosts.Contains(host)))
        { context.Response.StatusCode = 400; return; }
        // The native startup document (and an external link) may navigate to the
        // public application from another origin. This never authorizes its API calls.
        if (context.Request.Path.StartsWithSegments("/app") &&
            (HttpMethods.IsGet(context.Request.Method) || HttpMethods.IsHead(context.Request.Method)))
        { await next(context); return; }
        if (!OriginAllowed(context)) { context.Response.StatusCode = 403; return; }
        if (!context.Request.Path.StartsWithSegments("/app")) context.Response.Headers.CacheControl = "no-store";
        if (context.Request.Path.StartsWithSegments("/gateway") || context.Request.Path.StartsWithSegments("/app"))
        { await next(context); return; }
        var anonymous = sessions.Anonymous;
        var session = Session(context);
        if (settings.Read().HasPassword && session is null)
        { await Unauthorized(context); return; }
        // Bind both HTTP streams and upgraded sockets to server-side revocation.
        // Closing their transport does not stop an independently managed AI run.
        using var registration = (session ?? anonymous).Revoked.Register(context.Abort);
        await next(context);
    }

    private bool OriginAllowed(HttpContext context)
    {
        var origin = context.Request.Headers.Origin.ToString();
        if (string.IsNullOrEmpty(origin)) return context.Request.Headers["Sec-Fetch-Site"] != "cross-site";
        if (origin.Equals(options.FrontendDevOrigin, StringComparison.OrdinalIgnoreCase)) return true;
        if (origin.Equals($"{context.Request.Scheme}://{context.Request.Host}", StringComparison.OrdinalIgnoreCase)) return true;
        // Explicit HTTPS proxy origins; forwarding headers never grant identity.
        return (Environment.GetEnvironmentVariable("TIANCE_GATEWAY_ALLOWED_ORIGINS") ?? "")
            .Split(',', StringSplitOptions.TrimEntries | StringSplitOptions.RemoveEmptyEntries)
            .Contains(origin, StringComparer.OrdinalIgnoreCase);
    }

    public static Task Unauthorized(HttpContext context)
    {
        context.Response.StatusCode = 401;
        return context.Response.WriteAsJsonAsync(new { error = new { code = "AUTHENTICATION_REQUIRED", message = "登录已失效，请输入访问密码。" } });
    }
}
