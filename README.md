# 🎥 Family Parameter Animator for Revit

**Family Parameter Animator** is a tool for **pyRevit** that automates the animation of family (or instance) parameters in Revit.
It steps through parameter values, exports each step as a PNG, and optionally builds them into a looping GIF.
Perfect for showing dynamic changes in heights, lengths, façade details, or any other numeric parameter.

---

## ⚙ Installation

1. Copy the entire `GIF.pushbutton` folder into your pyRevit extensions directory, e.g.:

   ```
   %appdata%\pyRevit\Extensions\MyExtension.extension\MyTab.panel\
   ```
2. Make sure the folder contains:

   ```
   script.py          # main Python script
   ui.xaml            # WPF UI
   icon.png
   icon.dark.png
   icon.ico
   bundle.yaml
   ```
3. Restart Revit or reload panels via pyRevit CLI:

   ```
   pyrevit attach
   ```

---

## 🏗 Supported environment

* Revit 2021 or newer
* pyRevit ≥ 4.8
* Windows (uses .NET Framework)
* Runs inside Revit with pyRevit — **not a standalone app**

---

## 🚀 What it does

* Select a family or specific instance from your active Revit project.
* Toggle between **type parameters** and **instance parameters**.
* Add multiple numeric parameters for animation with individual **Min** / **Max** ranges.
* Two modes:

  * **Manual frames** — specify the exact number of frames (e.g. `10`).
  * **By duration and FPS** — set duration (sec) and FPS, calculates frames automatically.
* Automatically exports PNG frames using `ExportImage`.
* Supports:

  * DPI (72, 150, 300, 600, 1200\* simulated)
  * Pixel sizes (1024, 2048, 4096, 8192)
  * Scale factors (0.25x – 4.0x + any custom value)
* Builds a GIF immediately after rendering, with optional infinite loop (Netscape2.0 extension).
* Live console shows detailed logs; progress bar shows processing.

---

## 🔩 Technical highlights

* Uses Revit’s `DB.ImageExportOptions` for rendering.
* Automatically clamps DPI × PixelSize × Scale to Revit’s **15,000 px per side limit**.
* GIF is created with .NET `System.Drawing` multi-frame encoder.
  Includes direct byte-patch to add Netscape loop extension for true infinite playback.
* Parameters are set via Revit `Transaction`, with auto view refresh for each step.
* Console inside the UI shows step-by-step logs in a terminal style.

---

## 🚀 How to use

1. Click the **Family Parameter Animator** button in your pyRevit panel.
2. In the UI:

   * Select a family or instance.
   * Add parameters and set Min / Max values.
   * Set number of frames or use Duration + FPS.
   * Choose output folder for PNG / GIF.
   * Adjust DPI, pixel size, and scale.
   * Enable GIF creation and looping if needed.
3. Click **Start**.
   The script will iterate over parameter values, render each step, and build a GIF.

---

## 🚨 Important limits

* All frames in the GIF must have identical dimensions.
  This is controlled by DPI + PixelSize + Scale settings.
* Revit’s hard limit is **15,000 px** on any side.
  The script will automatically adjust scale to avoid errors.
* For best stability, stay at DPI ≤ 600 (1200 is “simulated” via scaling).

---

## 📝 Example `bundle.yaml`

```yaml
title: Create Animation GIF
tooltip: Animate family parameters and create GIF
author: Niko G.
script: script.py
icon: icon.png
largeicon: icon.png
darkicon: icon.dark.png
```

---

## 👤 Author

**Niko Gamsakhurdiya**
LinkedIn: [@nikogamsakhurdiya](https://www.linkedin.com/in/nikogamsakhurdiya)

