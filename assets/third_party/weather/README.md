# Candidate weather animation assets

These files are retained as candidates for the system-animation rainwater input.
All three sources label the artwork CC0 (public domain dedication).

## Weather Icon Set

- Author: Firefly in the Dusk
- Source: https://opengameart.org/content/weather-icons
- License: CC0; attribution is not required
- Original archive: `weather-icon-set.zip`
- Extracted files: `weather-icon-set/`
- Most applicable images: `sunnyWeather.png` and `rainyWeather.png`

## Rain Particle Animated

- Author: donte
- Source: https://opengameart.org/content/rain-particle-animated
- License: CC0; commercial use is permitted and credit is not required
- Original archive: `rain-drop-animation.zip`
- Extracted frames: `rain-drop-animation/rain_drop_0.png` through `rain_drop_4.png`

## Swapshot Rain animations

- Author: Gelatinousfox
- Source: https://opengameart.org/content/swapshot-rain-animations
- License: CC0
- Downloaded sprite sheet: `swapshot-rain-animation.png`

## Proposed application workflow

1. Keep the original archives and this provenance file in source control.
2. Select and normalize the desired frames into an application-owned folder such
   as `assets/weather_animation/`; use PNG frames rather than relying on GIF
   playback support.
3. Load frames once at application startup with `tk.PhotoImage` and retain Python
   references for the lifetime of the UI.
4. Choose the sunny image when `CollectedGallons` is zero. When it is positive,
   draw only the current rain-particle frame inside the Rainwater Input block,
   advancing it from the animation player's existing phase/timer.
5. Add the selected asset directory to `RainwaterCalculator.spec`, for example
   `("assets/weather_animation", "assets/weather_animation")`, so PyInstaller
   includes it. Resolve paths through the existing `_resource_path` helper.
6. Keep the current canvas-drawn weather as a fallback if assets cannot be loaded.
