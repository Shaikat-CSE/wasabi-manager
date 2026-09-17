# Sugarclass Mobile Reels — Developer Access

## Storage location

```text
Endpoint: https://s3.ap-southeast-1.wasabisys.com
Region: ap-southeast-1
Bucket: sugarclass-shared
```

## Credentials

```text
Access key: RAIU1II73LDO3AU3YLH6
Secret key: qNtpzzusHko0AzsUqLi2UF8QSB4JKQ14r92zeWQH
```

## Biology reels

```text
reels/igcse/cie/0610/biology/
```

Structure:

```text
reels/
└── igcse/
    └── cie/
        └── 0610/
            └── biology/
                ├── 01-characteristics-classification-of-living-organisms-slideshow.mp4
                ├── 02-cells-slideshow.mp4
                ├── ...
                └── build-slideshow/
                    ├── 13-1-excretion/
                    │   ├── slide.json
                    │   ├── slidescript.json
                    │   ├── frames/
                    │   │   └── slide_01.png
                    │   └── final/
                    │       ├── with_subs.mp4
                    │       ├── with_vo.mp4
                    │       ├── full.srt
                    │       └── vo_mix.wav
                    └── ...
```

## Recommended folder convention

```text
reels/<syllabus>/<board>/<code>/<subject>/
```

Example:

```text
reels/igcse/cie/0610/biology/
reels/igcse/edexcel/4bi1/biology/
reels/a-level/cie/9709/maths/
```

## File formats

| Type | Use |
|---|---|
| `with_subs.mp4` | Silent autoplay with burned-in subtitles |
| `with_vo.mp4` | Voiceover narration |
| `full.srt` | Subtitle file |
| `slide.json` | Slide metadata |
| `slidescript.json` | Voiceover script |
| `frames/*.png` | Thumbnail/preview frames |

## Mobile playback

### React Native / Expo

```tsx
<Video
  source={{ uri: reel.video_url }}
  useNativeControls
  resizeMode="contain"
  shouldPlay={false}
  isLooping={false}
  style={{ width: '100%', aspectRatio: 9 / 16 }}
/>
```

### Flutter

```dart
final controller = VideoPlayerController.networkUrl(
  Uri.parse(reel.videoUrl),
);
await controller.initialize();
```

## Backend guidance

The mobile app should never embed these credentials directly. Use a backend service to authenticate users and generate short-lived presigned URLs.

### Recommended API contract

```http
GET /api/mobile/v1/subjects/igcse_cie_biology_0610/reels
Authorization: Bearer <user-token>
```

Example response:

```json
{
  "subject_id": "igcse_cie_biology_0610",
  "items": [
    {
      "id": "13-1-excretion",
      "title": "Excretion",
      "video_url": "https://s3.ap-southeast-1.wasabisys.com/...signed-query...",
      "thumbnail_url": "https://s3.ap-southeast-1.wasabisys.com/...signed-query...",
      "captions_url": "https://s3.ap-southeast-1.wasabisys.com/...signed-query...",
      "expires_at": "2026-08-27T15:00:00Z"
    }
  ]
}
```

### Presigned URL generation (Python)

```python
import boto3

s3 = boto3.client("s3",
  endpoint_url="https://s3.ap-southeast-1.wasabisys.com",
  aws_access_key_id="RAIU1II73LDO3AU3YLH6",
  aws_secret_access_key="qNtpzzusHko0AzsUqLi2UF8QSB4JKQ14r92zeWQH"
)

url = s3.generate_presigned_url(
  "get_object",
  Params={
    "Bucket": "sugarclass-shared",
    "Key": "reels/igcse/cie/0610/biology/13-1-excretion/final/with_subs.mp4"
  },
  ExpiresIn=3600
)
```

### Key rules

- Generate URLs server-side only
- Set `ExpiresIn` to 3600 seconds (1 hour)
- Refresh URLs before expiry
- Never embed credentials in the mobile app
- Never persist presigned URLs across app restarts
