# astrbot_plugin_sing · AI Singing & Cover (StepFun)

Turn "play a song" into "actually sing" for AstrBot: generate a full song with vocals and
backing track from a topic, or re-sing a reference track in a different style, using
**StepAudio 3 Music** from StepFun.

> The singing model `stepaudio-3-music-preview` is currently **free for a limited time**.
> Swap the model id in the plugin config once the official paid model is released.

## Features

- `/唱歌 <topic>` — write lyrics and generate a complete song, sent as a voice message
- `/翻唱` — send or quote a track or video, or provide a public audio/Bilibili/YouTube URL, to generate a cover-style version
- `--干声` — keep the reference timbre, regenerate only the backing track
- Parameters: `--风格` style, `--音色` voice preset, `--歌词` lyrics, `--纯音乐` instrumental, `--音频` URL
- LLM tools `sing_song` / `cover_song` for natural-language triggering
- Per-session daily quota, per-session serialization, global concurrency of 2, background generation

## Install

Once the plugin is listed in the AstrBot market, search for **AI 唱歌与翻唱**. Until then, install manually:

```bash
cd AstrBot/data/plugins
git clone https://github.com/lovecodemaomao/astrbot_plugin_sing
pip install -r astrbot_plugin_sing/requirements.txt
```

## Configuration

Set `api_key` (required) in the plugin config. Get one at <https://platform.stepfun.com>.
See `_conf_schema.json` for every option.

## Usage

```
/唱歌 夏天的海
/唱歌 加班 --风格 "慵懒 lo-fi" --音色 御姐
/翻唱                       # attach or quote an audio file
/翻唱 --风格 摇滚 --干声
/翻唱 https://www.bilibili.com/video/BVxxxxxxxxxx --音色 少女
```

Values containing spaces must be quoted.

## Notes

- Generation may take several minutes. Long results are split into approximately 55-second voice messages for QQ.
- Video URLs are fetched with yt-dlp; some sites may block cloud-server downloads. Sending the video or MP3 as a QQ attachment remains available.
- Voice delivery requires FFmpeg in the runtime.

## Compliance

Use the cover feature only with audio you are authorised to process. Do not upload or
redistribute copyrighted recordings. Label AI-generated content where required by law.

## License

MIT
