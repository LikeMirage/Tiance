using System.Net;
using System.Net.Http.Json;
using System.Threading.Channels;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;
using Tiance.RemoteGateway;
using Xunit;

public sealed class LoginRateLimitingTests
{
    [Fact]
    public async Task SixthAttemptIsRejectedBeforeHandlerWithRetryAfter()
    {
        var calls = 0;
        await using var app = await StartApp(context =>
        {
            Interlocked.Increment(ref calls);
            context.Response.StatusCode = 401;
            return Task.CompletedTask;
        });
        using var client = app.GetTestClient();
        for (var index = 0; index < 5; index++)
        {
            using var allowed = await Login(client, "192.0.2.1");
            Assert.Equal(HttpStatusCode.Unauthorized, allowed.StatusCode);
        }
        using var rejected = await Login(client, "192.0.2.1");
        Assert.Equal(HttpStatusCode.TooManyRequests, rejected.StatusCode);
        Assert.InRange(rejected.Headers.RetryAfter!.Delta!.Value.TotalSeconds, 1, 60);
        Assert.Contains("LOGIN_RATE_LIMITED", await rejected.Content.ReadAsStringAsync());
        Assert.Equal(5, calls);
        using var otherIp = await Login(client, "192.0.2.2");
        Assert.Equal(HttpStatusCode.Unauthorized, otherIp.StatusCode);
        using var status = await client.GetAsync("/gateway/security/status");
        Assert.Equal(HttpStatusCode.OK, status.StatusCode);
    }

    [Fact]
    public async Task SuccessfulLoginsAlsoCountAndForwardingHeadersCannotBypassLimit()
    {
        await using var app = await StartApp(_ => Task.CompletedTask);
        using var client = app.GetTestClient();
        for (var index = 0; index < 5; index++)
        {
            using var allowed = await Login(client, "192.0.2.1", forwardedFor: $"198.51.100.{index}");
            Assert.Equal(HttpStatusCode.OK, allowed.StatusCode);
        }
        using var rejected = await Login(client, "::ffff:192.0.2.1", "/GATEWAY/security/login/", "203.0.113.1");
        Assert.Equal(HttpStatusCode.TooManyRequests, rejected.StatusCode);
    }

    [Fact]
    public async Task GlobalConcurrencyIsBoundedAcrossIpsAndReleasedAfterCompletion()
    {
        var entered = Channel.CreateUnbounded<bool>();
        var release = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        await using var app = await StartApp(async context =>
        {
            await entered.Writer.WriteAsync(true);
            await release.Task.WaitAsync(context.RequestAborted);
        });
        using var client = app.GetTestClient();
        var first = Login(client, "192.0.2.1");
        var second = Login(client, "192.0.2.2");
        try
        {
            await entered.Reader.ReadAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
            await entered.Reader.ReadAsync().AsTask().WaitAsync(TimeSpan.FromSeconds(5));
            using var rejected = await Login(client, "192.0.2.3", "/gateway/security/login/");
            Assert.Equal(HttpStatusCode.TooManyRequests, rejected.StatusCode);
            Assert.Contains("LOGIN_BUSY", await rejected.Content.ReadAsStringAsync());
            Assert.Equal(TimeSpan.FromSeconds(1), rejected.Headers.RetryAfter!.Delta);
            using var status = await client.GetAsync("/gateway/security/status");
            Assert.Equal(HttpStatusCode.OK, status.StatusCode);
        }
        finally
        {
            release.TrySetResult();
            using var firstResponse = await first;
            using var secondResponse = await second;
        }
        using var afterRelease = await Login(client, "192.0.2.3");
        Assert.Equal(HttpStatusCode.OK, afterRelease.StatusCode);
    }

    [Fact]
    public async Task ExceptionsReleaseConcurrencyPermits()
    {
        await using var app = await StartApp(_ => throw new InvalidOperationException("fixture"));
        using var client = app.GetTestClient();
        for (var index = 1; index <= 4; index++)
        {
            using var response = await Login(client, $"192.0.2.{index}");
            Assert.Equal(HttpStatusCode.InternalServerError, response.StatusCode);
        }
    }

    private static async Task<WebApplication> StartApp(RequestDelegate handler)
    {
        var builder = WebApplication.CreateBuilder();
        builder.WebHost.UseTestServer();
        builder.Services.AddRateLimiter(LoginRateLimiting.Configure);
        var app = builder.Build();
        app.Use(async (context, next) =>
        {
            // TestServer has no real peer; this header is only interpreted by this test host.
            context.Connection.RemoteIpAddress = IPAddress.Parse(context.Request.Headers["Test-Peer"].FirstOrDefault() ?? "192.0.2.1");
            try { await next(context); }
            catch (InvalidOperationException) { context.Response.StatusCode = 500; }
        });
        app.UseRouting();
        app.UseRateLimiter();
        app.MapPost("/gateway/security/login", handler).RequireRateLimiting(LoginRateLimiting.PolicyName);
        app.MapGet("/gateway/security/status", () => Results.Ok());
        await app.StartAsync();
        return app;
    }

    private static Task<HttpResponseMessage> Login(HttpClient client, string peer,
        string path = "/gateway/security/login", string? forwardedFor = null)
    {
        var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = JsonContent.Create(new { password = "test-password" }),
        };
        request.Headers.Add("Test-Peer", peer);
        if (forwardedFor is not null) request.Headers.Add("X-Forwarded-For", forwardedFor);
        return client.SendAsync(request);
    }
}
