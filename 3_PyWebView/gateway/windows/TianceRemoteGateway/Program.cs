using System.Net;
using System.Security.Cryptography.X509Certificates;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Yarp.ReverseProxy.Configuration;
using Yarp.ReverseProxy.Transforms;

namespace Tiance.RemoteGateway;

internal static class Program
{
    public static void Main(string[] args)
    {
        var options = GatewayOptions.FromEnvironment();
        var bootstrap = GatewayBootstrap.Read();
        var settingsStore = new GatewaySettingsStore(options.DataRoot);
        var sessions = new SessionStore();
        var security = new GatewaySecurity(options, settingsStore, sessions, bootstrap);
        var initialSettings = settingsStore.Read();

        var builder = WebApplication.CreateBuilder(args);
        builder.WebHost.ConfigureKestrel(server =>
        {
            if (options.ExternalAccessEnabled && initialSettings.HttpsEnabled)
            {
                server.ListenLocalhost(options.HttpPort);
                var certificate = LoadCertificate(initialSettings);
                server.ListenAnyIP(initialSettings.HttpsPort, listen => listen.UseHttps(certificate));
            }
            else
            {
                server.Listen(IPAddress.Parse(options.ListenHost), options.HttpPort);
            }
        });
        builder.Services.AddCors(cors => cors.AddDefaultPolicy(policy =>
        {
            if (!string.IsNullOrWhiteSpace(options.FrontendDevOrigin))
                policy.WithOrigins(options.FrontendDevOrigin).AllowAnyHeader().AllowAnyMethod().AllowCredentials();
        }));
        builder.Services.AddSingleton(settingsStore);
        builder.Services.AddSingleton(sessions);
        builder.Services.AddRateLimiter(LoginRateLimiting.Configure);
        builder.Services.AddReverseProxy().AddTransforms(transforms => transforms.AddRequestTransform(context =>
        {
            context.ProxyRequest.Headers.Remove(GatewayBootstrap.InternalHeader);
            context.ProxyRequest.Headers.TryAddWithoutValidation(GatewayBootstrap.InternalHeader, bootstrap.BackendToken);
            // Browser and desktop credentials belong to the gateway, never the Python backend.
            context.ProxyRequest.Headers.Remove("Cookie");
            return ValueTask.CompletedTask;
        })).LoadFromMemory(
            new[] { new RouteConfig { RouteId = "backend", ClusterId = "backend", Match = new RouteMatch { Path = "{**catch-all}" } } },
            new[] { new ClusterConfig { ClusterId = "backend", Destinations = new Dictionary<string, DestinationConfig> { ["backend"] = new() { Address = options.BackendUrl } } } });

        var app = builder.Build();
        app.UseRouting();
        app.UseCors();
        app.UseRateLimiter();
        app.UseWebSockets();
        app.Use(security.Invoke);
        using var sessionSweep = new Timer(_ => sessions.Sweep(), null, TimeSpan.FromSeconds(15), TimeSpan.FromSeconds(15));
        app.Lifetime.ApplicationStopping.Register(sessions.Clear);

        app.MapGet("/gateway/health", () => Results.Ok(new { ok = true, security_protocol = 2 }));
        app.MapGet("/gateway/security/status", (HttpContext context) =>
        {
            var settings = settingsStore.Read();
            var session = security.Session(context);
            var localBypass = session?.IsDesktop == true;
            var authenticated = !settings.HasPassword || session is not null;
            return Results.Ok(new
            {
                password_configured = settings.HasPassword,
                local_bypass_enabled = settings.LocalBypassEnabled,
                local_bypass_active = localBypass,
                authenticated,
                session_kind = !settings.HasPassword ? "none" : localBypass ? "desktop" : session is not null ? "browser" : "none",
                https_enabled = settings.HttpsEnabled,
                https_port = settings.HttpsPort,
                certificate_path = authenticated ? settings.CertificatePath : "",
                restart_required = RequiresRestart(initialSettings, settings),
            });
        });
        app.MapPost("/gateway/security/login", async (HttpContext context, [FromBody] LoginRequest request) =>
        {
            var settings = settingsStore.Read();
            if (!settings.HasPassword || !await PasswordService.VerifyAsync(request.Password, settings))
                return Results.Json(new { error = new { code = "INVALID_PASSWORD", message = "密码错误。" } }, statusCode: 401);
            AppendSessionCookie(context, sessions.Create(), context.Request.IsHttps);
            return Results.Ok(new { authenticated = true });
        }).RequireRateLimiting(LoginRateLimiting.PolicyName);
        app.MapPost("/gateway/security/logout", (HttpContext context) =>
        {
            sessions.Remove(context.Request.Cookies[SessionStore.CookieName]);
            DeleteSessionCookie(context);
            return Results.Ok(new { authenticated = false });
        });
        app.MapPut("/gateway/security/password", async (HttpContext context, [FromBody] PasswordUpdateRequest request) =>
        {
            var current = settingsStore.Read();
            if (!current.HasPassword && !security.IsDesktop(context))
                return Results.Json(new { error = new { code = "LOCAL_SETUP_REQUIRED", message = "首次设置访问密码必须在天策桌面客户端中完成。" } }, statusCode: 403);
            if (current.HasPassword && !security.Authorized(context))
                return Results.Unauthorized();
            if (current.HasPassword && !await PasswordService.VerifyAsync(request.CurrentPassword ?? "", current))
                return Results.Json(new { error = new { code = "INVALID_CURRENT_PASSWORD", message = "当前密码错误。" } }, statusCode: 400);
            var (hash, salt) = await PasswordService.HashAsync(request.NewPassword);
            settingsStore.Update(value => value with { PasswordHash = hash, PasswordSalt = salt });
            sessions.Clear();
            AppendSessionCookie(context, sessions.Create(), context.Request.IsHttps);
            return Results.Ok(new { password_configured = true });
        });
        app.MapDelete("/gateway/security/password", async (HttpContext context, [FromBody] PasswordRemoveRequest request) =>
        {
            var current = settingsStore.Read();
            if (!current.HasPassword) return Results.Ok(new { password_configured = false });
            if (!security.Authorized(context)) return Results.Unauthorized();
            if (!await PasswordService.VerifyAsync(request.CurrentPassword, current))
                return Results.Json(new { error = new { code = "INVALID_CURRENT_PASSWORD", message = "当前密码错误。" } }, statusCode: 400);
            settingsStore.Update(value => value with { PasswordHash = null, PasswordSalt = null });
            sessions.Clear();
            DeleteSessionCookie(context);
            return Results.Ok(new { password_configured = false });
        });
        app.MapPut("/gateway/security/settings", (HttpContext context, [FromBody] SecuritySettingsRequest request) =>
        {
            var current = settingsStore.Read();
            if (!current.HasPassword && !security.IsDesktop(context)) return Results.Unauthorized();
            if (current.HasPassword && !security.Authorized(context)) return Results.Unauthorized();
            if (request.HttpsPort is < 1 or > 65535)
                return Results.BadRequest(new { error = new { code = "INVALID_HTTPS_PORT", message = "HTTPS 端口必须在 1 到 65535 之间。" } });
            if (request.HttpsEnabled)
            {
                var candidate = current with
                {
                    HttpsEnabled = true,
                    HttpsPort = request.HttpsPort,
                    CertificatePath = request.CertificatePath.Trim(),
                    ProtectedCertificatePassword = request.CertificatePassword is null
                        ? current.ProtectedCertificatePassword
                        : GatewaySettingsStore.ProtectSecret(request.CertificatePassword),
                };
                _ = LoadCertificate(candidate);
            }
            var updated = settingsStore.Update(value => value with
            {
                LocalBypassEnabled = request.LocalBypassEnabled,
                HttpsEnabled = request.HttpsEnabled,
                HttpsPort = request.HttpsPort,
                CertificatePath = request.CertificatePath.Trim(),
                ProtectedCertificatePassword = request.CertificatePassword is null
                    ? value.ProtectedCertificatePassword
                    : GatewaySettingsStore.ProtectSecret(request.CertificatePassword),
            });
            if (current.LocalBypassEnabled != updated.LocalBypassEnabled) sessions.ResetDesktopConnections();
            return Results.Ok(new { restart_required = RequiresRestart(initialSettings, updated) });
        });
        app.MapPost("/gateway/security/sessions/revoke", (HttpContext context) =>
        {
            var current = settingsStore.Read();
            if (current.HasPassword && !security.Authorized(context)) return Results.Unauthorized();
            sessions.Clear();
            return Results.Ok(new { revoked = true });
        });
        app.MapPost("/gateway/security/session", async (HttpContext context, [FromBody] SessionPresenceRequest request) =>
        {
            if (!settingsStore.Read().HasPassword || security.Session(context)?.IsDesktop == true)
            { await context.Response.WriteAsJsonAsync(new { authenticated = true }); return; }
            if (!sessions.Touch(context.Request.Cookies[SessionStore.CookieName], request.PageId, request.Activity))
            { await GatewaySecurity.Unauthorized(context); return; }
            await context.Response.WriteAsJsonAsync(new { authenticated = true });
        });
        app.MapPost("/gateway/security/session/leave", (HttpContext context, [FromBody] SessionPresenceRequest request) =>
        {
            sessions.Leave(context.Request.Cookies[SessionStore.CookieName], request.PageId);
            return Results.NoContent();
        });
        app.MapReverseProxy();
        app.Run();
    }

    private static bool RequiresRestart(GatewaySettings running, GatewaySettings configured) =>
        running.HttpsEnabled != configured.HttpsEnabled
        || running.HttpsPort != configured.HttpsPort
        || !string.Equals(running.CertificatePath, configured.CertificatePath, StringComparison.OrdinalIgnoreCase)
        || !string.Equals(running.ProtectedCertificatePassword, configured.ProtectedCertificatePassword, StringComparison.Ordinal);

    private static void AppendSessionCookie(HttpContext context, string token, bool secure) =>
        context.Response.Cookies.Append(SessionStore.CookieName, token, new CookieOptions
        {
            HttpOnly = true,
            SameSite = SameSiteMode.Strict,
            Secure = secure,
            Path = "/",
        });

    private static void DeleteSessionCookie(HttpContext context) =>
        context.Response.Cookies.Delete(SessionStore.CookieName, new CookieOptions
        {
            HttpOnly = true,
            SameSite = SameSiteMode.Strict,
            Secure = context.Request.IsHttps,
            Path = "/",
        });

    private static X509Certificate2 LoadCertificate(GatewaySettings settings)
    {
        if (string.IsNullOrWhiteSpace(settings.CertificatePath) || !File.Exists(settings.CertificatePath))
            throw new InvalidOperationException("启用 HTTPS 前必须选择有效的 PFX 证书文件。");
#pragma warning disable SYSLIB0057
        return new X509Certificate2(
            settings.CertificatePath,
            GatewaySettingsStore.UnprotectSecret(settings.ProtectedCertificatePassword),
            X509KeyStorageFlags.EphemeralKeySet);
#pragma warning restore SYSLIB0057
    }
}

internal sealed record LoginRequest(string Password);
internal sealed record SessionPresenceRequest(string PageId, bool Activity = false);
internal sealed record PasswordUpdateRequest(string? CurrentPassword, string NewPassword);
internal sealed record PasswordRemoveRequest(string CurrentPassword);
internal sealed record SecuritySettingsRequest(bool LocalBypassEnabled, bool HttpsEnabled, int HttpsPort, string CertificatePath, string? CertificatePassword);

internal sealed record GatewayOptions(string ListenHost, int HttpPort, string BackendUrl, string DataRoot, bool ExternalAccessEnabled, string FrontendDevOrigin)
{
    public static GatewayOptions FromEnvironment() => new(
        Required("TIANCE_GATEWAY_HOST"),
        ParsePort("TIANCE_GATEWAY_PORT"),
        EnsureTrailingSlash(Required("TIANCE_BACKEND_URL")),
        Required("TIANCE_DATA_ROOT"),
        string.Equals(Environment.GetEnvironmentVariable("TIANCE_EXTERNAL_ACCESS_ENABLED"), "true", StringComparison.OrdinalIgnoreCase),
        Environment.GetEnvironmentVariable("TIANCE_FRONTEND_DEV_URL")?.Trim() ?? "");

    private static string Required(string name) => Environment.GetEnvironmentVariable(name)?.Trim() is { Length: > 0 } value
        ? value
        : throw new InvalidOperationException($"Missing required environment variable: {name}");
    private static int ParsePort(string name) => int.TryParse(Required(name), out var port) && port is > 0 and <= 65535
        ? port
        : throw new InvalidOperationException($"Invalid port in environment variable: {name}");
    private static string EnsureTrailingSlash(string value) => value.EndsWith('/') ? value : value + "/";
}
