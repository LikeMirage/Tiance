using System.Collections.Concurrent;
using System.Security.Cryptography;

namespace Tiance.RemoteGateway;

internal sealed class SessionStore
{
    public const string CookieName = "tiance_access_session";
    private readonly ConcurrentDictionary<string, byte> _sessions = new();

    public string Create()
    {
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        _sessions[token] = 0;
        return token;
    }

    public bool IsValid(string? token) =>
        !string.IsNullOrWhiteSpace(token) && _sessions.ContainsKey(token);

    public void Remove(string? token)
    {
        if (!string.IsNullOrWhiteSpace(token)) _sessions.TryRemove(token, out _);
    }

    public void Clear() => _sessions.Clear();
}
