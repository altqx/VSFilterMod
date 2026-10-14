Usage
=====

    vsfm.TextSubMod(clip clip, string file[, int charset=1, float fps=-1.0, string vfr='', int accurate=0])
    vsfm.VobSub(clip clip, string file[, int accurate=0, int track, int delay, int forced,
                string colors, string tridx, string palette, int x, int y, int scale_x, int scale_y,
                int alpha, string align])

* clip: Clip to process. Only YUV420P8, YUV420P10, YUV420P16 and RGB24 are supported.
* accurate: 1: enable accurate render for 10/16bit (~2x slower). / 0: disable (default)

AviSynth takes the same VobSub options by name:

    VobSub(clip, string file, int "track", int "delay", bool "forced", string "colors", string "tridx",
           string "palette", int "x", int "y", int "scale_x", int "scale_y", int "alpha", string "align")

VobSub options
-----
They are the settings of the .idx file; an option left out keeps the .idx value.

* track: language index of the .idx (`id: en, index: 1` is track 1).
* delay: ms; positive shows the subtitles later, negative earlier.
* forced: 1/true shows only forced subtitles.
* colors: custom colours `"RRGGBB,RRGGBB,RRGGBB,RRGGBB"` for background, pattern, emphasis 1 and 2;
  turns custom colours on. tridx: which of them are transparent, as in the .idx (`"1000"`: background).
* palette: 16 `RRGGBB` colours separated by commas, replacing the .idx palette.
* x, y: position (`org`) in the pixels of the .idx `size`.
* scale_x, scale_y: size in %. alpha: opacity in % (0-100).
* align: `"off"`, or `"<left|center|right> <top|center|bottom>"` to place the picture by that point at x, y.

\$img
-----
`\$img(path[,xoffset,yoffset])` fills with a repeated PNG. The path may use `/` or `\`. Images attached
to the script (its `[Graphics]` section, or the attachments of a Matroska file in DirectShow) are used
first, matched by file name without case; then the path is tried as given and relative to the script.

Knowing Issues
=====
* Opentype font (such as Source Han Sans) has a much smaller size when displayed vertically (used like @Source Han Sans). (subtitle renders which origin from VSFilter use GDI to render fonts, but GDI performs badly on opentype fonts.)

Use VSFilterMod in MPC-BE
====
1. run `regsvr32.exe VSFilterMod.dll` with administrator privileges
2. Select "VSFilter/xy-VSFilter" on the select of Options/Subtitles/Subtitle renderer