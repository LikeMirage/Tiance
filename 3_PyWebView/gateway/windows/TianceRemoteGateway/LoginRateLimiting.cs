using System.Globalization;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.RateLimiting;

namespace Tiance.RemoteGateway;

internal static class LoginRateLimiting
{
    internal const string PolicyName = "gateway-login";

    public static void Configure(RateLimiterOptions options)
    {
        options.AddPolicy(PolicyName, context =>
        {
            // Use the connection address, never untrusted forwarding headers.
            var address = context.Connection.RemoteIpAddress;
            if (address?.IsIPv4MappedToIPv6 == true) address = address.MapToIPv4();
            return RateLimitPartition.GetFixedWindowLimiter(address?.ToString() ?? "unknown", _ => new()
            {
                PermitLimit = 5,
                Window = TimeSpan.FromMinutes(1),
                QueueLimit = 0,
                AutoReplenishment = true,
            });
        });

        // Bound expensive Argon2 work across all IPs, without queuing login requests.
        // Endpoint metadata also covers alternate casing and trailing slashes.
        options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(context =>
            context.GetEndpoint()?.Metadata.GetMetadata<EnableRateLimitingAttribute>()?.PolicyName == PolicyName
                ? RateLimitPartition.GetConcurrencyLimiter(PolicyName, _ => new()
                {
                    PermitLimit = 2,
                    QueueLimit = 0,
                })
                : RateLimitPartition.GetNoLimiter("other-endpoints"));

        options.OnRejected = async (context, cancellationToken) =>
        {
            var limitedByWindow = context.Lease.TryGetMetadata(MetadataName.RetryAfter, out var retryAfter);
            var seconds = limitedByWindow ? Math.Max(1, (int)Math.Ceiling(retryAfter.TotalSeconds)) : 1;
            var response = context.HttpContext.Response;
            response.StatusCode = StatusCodes.Status429TooManyRequests;
            response.Headers.RetryAfter = seconds.ToString(CultureInfo.InvariantCulture);
            await response.WriteAsJsonAsync(new
            {
                error = new
                {
                    code = limitedByWindow ? "LOGIN_RATE_LIMITED" : "LOGIN_BUSY",
                    message = limitedByWindow
                        ? $"登录过于频繁，每分钟最多 5 次，请在 {seconds} 秒后重试。"
                        : "登录验证繁忙，请在 1 秒后重试。",
                },
            }, cancellationToken);
        };
    }
}
