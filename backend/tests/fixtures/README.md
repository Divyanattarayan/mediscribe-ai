# Test Fixtures

This directory holds the audio fixtures used to exercise the transcription pipeline end to end.

## Files

| File | Purpose |
| --- | --- |
| `test11-yt_chest_pain.mp3` | Mock chest-pain consultation. Used as the canonical sample for the smoke test. ~3 minutes, MP3, mono. |

## How the smoke test uses the fixture

`scripts/smoke-test.sh` uploads `test11-yt_chest_pain.mp3` to a running local backend through `POST /api/transcribe`. The expected pipeline result:

- Backend accepts the upload (passes the 45-second minimum-duration guard).
- Content validation passes (clinical conversation).
- Entity extraction returns a non-empty list.
- SOAP generation returns populated `subjective`, `objective`, `assessment`, `plan` strings.
- The transcription is persisted and returned by `GET /api/history`.

## Replacing or adding fixtures

To replace the chest-pain sample with a different clip, drop the new file in this directory and update `SAMPLE_AUDIO` in `scripts/smoke-test.sh`. Audio must be:

- At least 45 seconds long
- A supported extension (`.mp3`, `.wav`, `.m4a`, `.webm`, `.ogg`, `.flac`)
- Genuinely clinical (otherwise content validation will reject it before SOAP generation runs)
