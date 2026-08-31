using System.Security.Cryptography;
using System.Text;
using Konscious.Security.Cryptography;

namespace Tiance.RemoteGateway;

internal static class PasswordService
{
    private const int SaltLength = 16;
    private const int HashLength = 32;
    private const int Iterations = 3;
    private const int MemorySizeKb = 65536;
    private const int Parallelism = 2;

    public static async Task<(string Hash, string Salt)> HashAsync(string password)
    {
        ValidatePassword(password);
        var salt = RandomNumberGenerator.GetBytes(SaltLength);
        var hash = await DeriveAsync(password, salt);
        return (Convert.ToBase64String(hash), Convert.ToBase64String(salt));
    }

    public static async Task<bool> VerifyAsync(string password, GatewaySettings settings)
    {
        if (!settings.HasPassword || string.IsNullOrEmpty(password)) return false;
        try
        {
            var salt = Convert.FromBase64String(settings.PasswordSalt!);
            var expected = Convert.FromBase64String(settings.PasswordHash!);
            var actual = await DeriveAsync(password, salt);
            return CryptographicOperations.FixedTimeEquals(actual, expected);
        }
        catch (FormatException) { return false; }
    }

    public static void ValidatePassword(string password)
    {
        if (password.Length < 8 || password.Length > 256)
            throw new ArgumentException("密码长度必须为 8 至 256 个字符。");
    }

    private static async Task<byte[]> DeriveAsync(string password, byte[] salt)
    {
        var passwordBytes = Encoding.UTF8.GetBytes(password);
        try
        {
            using var argon2 = new Argon2id(passwordBytes)
            {
                Salt = salt,
                DegreeOfParallelism = Parallelism,
                Iterations = Iterations,
                MemorySize = MemorySizeKb,
            };
            return await argon2.GetBytesAsync(HashLength);
        }
        finally { CryptographicOperations.ZeroMemory(passwordBytes); }
    }
}
