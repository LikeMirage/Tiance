using System.Security.Cryptography;
using System.Text;

namespace Tiance.RemoteGateway;

internal sealed class SessionStore : IDisposable
{
    public const string CookieName = "tiance_access_session";
    public const string DesktopCookieName = "tiance_desktop_session";
    internal static readonly TimeSpan IdleTimeout = TimeSpan.FromHours(1);
    internal static readonly TimeSpan AbsoluteTimeout = TimeSpan.FromHours(24);
    internal static readonly TimeSpan PresenceTimeout = TimeSpan.FromSeconds(90);
    internal static readonly TimeSpan ReconnectGrace = TimeSpan.FromSeconds(15);
    private readonly object _gate = new();
    private readonly Dictionary<string, AccessSession> _sessions = new();
    private readonly TimeProvider _clock;
    private AccessSession _desktop;
    private AccessSession _anonymous;

    public SessionStore(TimeProvider? clock = null)
    {
        _clock = clock ?? TimeProvider.System;
        _desktop = new AccessSession(_clock.GetUtcNow(), true);
        _anonymous = new AccessSession(_clock.GetUtcNow(), true);
    }

    public string Create()
    {
        var token = Convert.ToHexString(RandomNumberGenerator.GetBytes(32)).ToLowerInvariant();
        AccessSession? evicted = null;
        lock (_gate)
        {
            if (_sessions.Count >= 256)
            {
                var oldest = _sessions.MinBy(entry => entry.Value.CreatedAt);
                _sessions.Remove(oldest.Key);
                evicted = oldest.Value;
            }
            _sessions.Add(Hash(token), new AccessSession(_clock.GetUtcNow(), false));
        }
        evicted?.Revoke();
        return token;
    }

    public AccessSession Desktop { get { lock (_gate) return _desktop; } }
    public AccessSession Anonymous { get { lock (_gate) return _anonymous; } }

    public AccessSession? Get(string? token)
    {
        if (token is null || token.Length != 64) return null;
        AccessSession? expired;
        lock (_gate)
        {
            var key = Hash(token);
            if (!_sessions.TryGetValue(key, out var session)) return null;
            if (session.IsValid(_clock.GetUtcNow())) return session;
            _sessions.Remove(key);
            expired = session;
        }
        expired.Revoke();
        return null;
    }

    public bool IsValid(string? token) => Get(token) is not null;

    public bool Touch(string? token, string pageId, bool activity)
    {
        var session = Get(token);
        return session is not null && session.Touch(pageId, activity, _clock.GetUtcNow());
    }

    public void Leave(string? token, string pageId) => Get(token)?.Leave(pageId, _clock.GetUtcNow());

    public void Remove(string? token)
    {
        if (token is null || token.Length != 64) return;
        AccessSession? removed;
        lock (_gate) _sessions.Remove(Hash(token), out removed);
        removed?.Revoke();
    }

    public void Clear()
    {
        AccessSession[] removed;
        lock (_gate) { removed = _sessions.Values.ToArray(); _sessions.Clear(); }
        foreach (var session in removed) session.Revoke();
        AccessSession anonymous;
        lock (_gate) { anonymous = _anonymous; _anonymous = new AccessSession(_clock.GetUtcNow(), true); }
        anonymous.Revoke();
        ResetDesktopConnections();
    }

    public void ResetDesktopConnections()
    {
        AccessSession previous;
        lock (_gate) { previous = _desktop; _desktop = new AccessSession(_clock.GetUtcNow(), true); }
        previous.Revoke();
    }

    public void Sweep()
    {
        List<AccessSession> expired = new();
        lock (_gate)
        {
            var now = _clock.GetUtcNow();
            foreach (var entry in _sessions.ToArray())
                if (!entry.Value.IsValid(now)) { _sessions.Remove(entry.Key); expired.Add(entry.Value); }
        }
        foreach (var session in expired) session.Revoke();
    }

    public void Dispose() { Clear(); Desktop.Revoke(); Anonymous.Revoke(); }
    private static string Hash(string token) => Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(token)));
}

internal sealed class AccessSession(DateTimeOffset now, bool desktop)
{
    private readonly object _gate = new();
    private readonly Dictionary<string, DateTimeOffset> _pages = new();
    private readonly Dictionary<string, DateTimeOffset> _closedPages = new();
    private readonly CancellationTokenSource _revocation = new();
    private DateTimeOffset _lastActivity = now;
    private DateTimeOffset _presenceDeadline = now + SessionStore.PresenceTimeout;
    public DateTimeOffset CreatedAt { get; } = now;
    public bool IsDesktop { get; } = desktop;
    public CancellationToken Revoked => _revocation.Token;

    public bool IsValid(DateTimeOffset current)
    {
        lock (_gate) return IsValidLocked(current);
    }

    private bool IsValidLocked(DateTimeOffset current) => !_revocation.IsCancellationRequested &&
        (IsDesktop || (current < CreatedAt + SessionStore.AbsoluteTimeout &&
         current < _lastActivity + SessionStore.IdleTimeout && current < _presenceDeadline));

    public bool Touch(string pageId, bool activity, DateTimeOffset current)
    {
        lock (_gate)
        {
            if (!IsValidLocked(current) || string.IsNullOrWhiteSpace(pageId) || pageId.Length > 80) return false;
            foreach (var stale in _closedPages.Where(p => p.Value <= current).Select(p => p.Key).ToArray()) _closedPages.Remove(stale);
            if (_closedPages.ContainsKey(pageId)) return false;
            foreach (var stale in _pages.Where(p => p.Value <= current).Select(p => p.Key).ToArray()) _pages.Remove(stale);
            if (!_pages.ContainsKey(pageId) && _pages.Count >= 128) return false;
            _pages[pageId] = current + SessionStore.PresenceTimeout;
            _presenceDeadline = _pages.Values.Max();
            if (activity) _lastActivity = current;
            return true;
        }
    }

    public void Leave(string pageId, DateTimeOffset current)
    {
        lock (_gate)
        {
            if (string.IsNullOrWhiteSpace(pageId) || pageId.Length > 80) return;
            if (_closedPages.Count < 256) _closedPages[pageId] = current + SessionStore.PresenceTimeout;
            if (!_pages.Remove(pageId)) return;
            var latest = _pages.Values.DefaultIfEmpty(current).Max();
            _presenceDeadline = latest > current ? latest : current + SessionStore.ReconnectGrace;
        }
    }

    public void Revoke() => _revocation.Cancel();
}
