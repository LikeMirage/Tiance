# SILK regression fixture

`tone.silk` contains a synthetic one-second 440 Hz sine wave, not a user recording.
The input is mono signed 16-bit little-endian PCM at 16,000 Hz, each sample
`round(6000 * sin(2 * pi * 440 * i / 16000))` for `i = 0..15999`.

Encoded with kn007/silk-v3-decoder at revision
`507be6bca8ce1fb977a061481f1d79e8c610e309`, using its
`windows/silk_v3_encoder.exe` and arguments
`tone.pcm tone.silk -Fs_API 16000 -quiet`.
Encoder SHA-256: `b79f27c19308c35b685a2ad5a680deaefa8a3e038dabb4aa926dc42467c6eef7`.
The encoder is only a fixture-generation dependency and is not bundled.

Native decoder tests require Windows; cloud requests are mocked.
