using System.Security.Cryptography;
using System.Text.Json;

namespace Tiance.RemoteGateway;

internal sealed record GatewaySettings(
    string? PasswordHash,
    string? PasswordSalt,
    bool LocalBypassEnabled,
    bool HttpsEnabled,
    int HttpsPort,
    string CertificatePath,
    string? ProtectedCertificatePassword)
{
    public const int CurrentVersion = 1;

    public bool HasPassword => !string.IsNullOrWhiteSpace(PasswordHash)
        && !string.IsNullOrWhiteSpace(PasswordSalt);

    public static GatewaySettings Empty { get; } = new(
        null,
        null,
        false,
        false,
        18443,
        "",
        null);
}

internal sealed class GatewaySettingsStore
{
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
        WriteIndented = true,
    };

    private readonly string _path;
    private readonly object _gate = new();
    private GatewaySettings _current;

    public GatewaySettingsStore(string dataRoot)
    {
        _path = Path.Combine(dataRoot, "security", "access-security.json");
        _current = Load();
    }

    public GatewaySettings Read()
    {
        lock (_gate) return _current;
    }

    public GatewaySettings Update(Func<GatewaySettings, GatewaySettings> update)
    {
        lock (_gate)
        {
            var next = update(_current);
            Save(next);
            _current = next;
            return next;
        }
    }

    private GatewaySettings Load()
    {
        if (!File.Exists(_path)) return GatewaySettings.Empty;
        try
        {
            using var document = JsonDocument.Parse(File.ReadAllBytes(_path));
            var root = document.RootElement;
            if (!root.TryGetProperty("version", out var version)
                || version.GetInt32() != GatewaySettings.CurrentVersion)
            {
                throw new InvalidDataException("Unsupported access security settings version.");
            }
            return JsonSerializer.Deserialize<GatewaySettings>(root.GetProperty("settings"), JsonOptions)
                ?? throw new InvalidDataException("Access security settings are empty.");
        }
        catch (Exception error)
        {
            throw new InvalidDataException($"Unable to read access security settings: {_path}", error);
        }
    }

    private void Save(GatewaySettings settings)
    {
        var directory = Path.GetDirectoryName(_path)!;
        Directory.CreateDirectory(directory);
        var temporaryPath = _path + ".tmp";
        var payload = JsonSerializer.SerializeToUtf8Bytes(new
        {
            version = GatewaySettings.CurrentVersion,
            settings,
        }, JsonOptions);
        File.WriteAllBytes(temporaryPath, payload);
        File.Move(temporaryPath, _path, true);
    }

    public static string ProtectSecret(string value)
    {
        var clear = System.Text.Encoding.UTF8.GetBytes(value);
        var protectedBytes = ProtectedData.Protect(clear, null, DataProtectionScope.CurrentUser);
        CryptographicOperations.ZeroMemory(clear);
        return Convert.ToBase64String(protectedBytes);
    }

    public static string UnprotectSecret(string? value)
    {
        if (string.IsNullOrWhiteSpace(value)) return "";
        var protectedBytes = Convert.FromBase64String(value);
        var clear = ProtectedData.Unprotect(protectedBytes, null, DataProtectionScope.CurrentUser);
        try { return System.Text.Encoding.UTF8.GetString(clear); }
        finally { CryptographicOperations.ZeroMemory(clear); }
    }
}
