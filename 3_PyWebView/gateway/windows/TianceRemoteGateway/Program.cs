using System.Net;
using System.Security.Cryptography.X509Certificates;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Yarp.ReverseProxy.Configuration;

namespace Tiance.RemoteGateway;

internal static class Program
{
    public static void Main(string[] args)
    {
        var options = GatewayOptions.FromEnvironment();
        var settingsStore = new GatewaySettingsStore(options.DataRoot);
        var sessions = new SessionStore();
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
        builder.Services.AddReverseProxy().LoadFromMemory(
            new[] { new RouteConfig { RouteId = "backend", ClusterId = "backend", Match = new RouteMatch { Path = "{**catch-all}" } } },
            new[] { new ClusterConfig { ClusterId = "backend", Destinations = new Dictionary<string, DestinationConfig> { ["backend"] = new() { Address = options.BackendUrl } } } });

        var app = builder.Build();
        app.UseCors();
        app.UseWebSockets();
        app.Use(async (context, next) =>
        {
            if (IsGatewayEndpoint(context.Request.Path) || IsPublicAppAsset(context.Request.Path))
            {
                await next();
                return;
            }
            var settings = settingsStore.Read();
            if (!settings.HasPassword || (settings.LocalBypassEnabled && IsLoopback(context.Connection.RemoteIpAddress)))
            {
                await next();
                return;
            }
            if (sessions.IsValid(context.Request.Cookies[SessionStore.CookieName]))
            {
                await next();
                return;
            }
            context.Response.StatusCode = StatusCodes.Status401Unauthorized;
            await context.Response.WriteAsJsonAsync(new { error = new { code = "AUTHENTICATION_REQUIRED", message = "需要输入访问密码。" } });
        });

        app.MapGet("/gateway/health", () => Results.Ok(new { ok = true }));
        app.MapGet("/gateway/security/status", (HttpContext context) =>
        {
            var settings = settingsStore.Read();
            var localBypass = settings.LocalBypassEnabled && IsLoopback(context.Connection.RemoteIpAddress);
            var authenticated = !settings.HasPassword || localBypass || sessions.IsValid(context.Request.Cookies[SessionStore.CookieName]);
            return Results.Ok(new
            {
                password_configured = settings.HasPassword,
                local_bypass_enabled = settings.LocalBypassEnabled,
                local_bypass_active = localBypass,
                authenticated,
                https_enabled = settings.HttpsEnabled,
                https_port = settings.HttpsPort,
                certificate_path = settings.CertificatePath,
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
        });
        app.MapPost("/gateway/security/logout", (HttpContext context) =>
        {
            sessions.Remove(context.Request.Cookies[SessionStore.CookieName]);
            DeleteSessionCookie(context);
            return Results.Ok(new { authenticated = false });
        });
        app.MapPut("/gateway/security/password", async (HttpContext context, [FromBody] PasswordUpdateRequest request) =>
        {
            var current = settingsStore.Read();
            if (!current.HasPassword && !IsLoopback(context.Connection.RemoteIpAddress))
                return Results.Json(new { error = new { code = "LOCAL_SETUP_REQUIRED", message = "首次设置访问密码必须在运行天策的电脑上完成。" } }, statusCode: 403);
            if (current.HasPassword && !IsAuthorized(context, current, sessions))
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
            if (!IsAuthorized(context, current, sessions)) return Results.Unauthorized();
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
            if (!current.HasPassword && !IsLoopback(context.Connection.RemoteIpAddress)) return Results.Unauthorized();
            if (current.HasPassword && !IsAuthorized(context, current, sessions)) return Results.Unauthorized();
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
            return Results.Ok(new { restart_required = RequiresRestart(initialSettings, updated) });
        });
        app.MapPost("/gateway/security/sessions/revoke", (HttpContext context) =>
        {
            var current = settingsStore.Read();
            if (current.HasPassword && !IsAuthorized(context, current, sessions)) return Results.Unauthorized();
            sessions.Clear();
            return Results.Ok(new { revoked = true });
        });
        app.MapReverseProxy();
        app.Run();
    }

    private static bool IsAuthorized(HttpContext context, GatewaySettings settings, SessionStore sessions) =>
        !settings.HasPassword
        || (settings.LocalBypassEnabled && IsLoopback(context.Connection.RemoteIpAddress))
        || sessions.IsValid(context.Request.Cookies[SessionStore.CookieName]);

    private static bool IsLoopback(IPAddress? address) => address is not null && IPAddress.IsLoopback(address);
    private static bool RequiresRestart(GatewaySettings running, GatewaySettings configured) =>
        running.HttpsEnabled != configured.HttpsEnabled
        || running.HttpsPort != configured.HttpsPort
        || !string.Equals(running.CertificatePath, configured.CertificatePath, StringComparison.OrdinalIgnoreCase)
        || !string.Equals(running.ProtectedCertificatePassword, configured.ProtectedCertificatePassword, StringComparison.Ordinal);
    private static bool IsGatewayEndpoint(PathString path) => path.StartsWithSegments("/gateway");
    private static bool IsPublicAppAsset(PathString path) => path.StartsWithSegments("/app");

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
