-- First-run defaults for KOReader on the Kobo (only installed if no settings exist).
return {
    ["home_dir"] = "/mnt/onboard/.adds/sefarim",
    ["lastdir"] = "/mnt/onboard/.adds/sefarim",
    ["start_with"] = "filemanager",
    ["language"] = "he",
    -- Hebrew book font with correct nikud + te'amim placement.
    ["cre_font"] = "Taamey Frank CLM",
    -- 3 = "best" (HarfBuzz): required for mark positioning.
    ["copt_font_kerning"] = 3,
    ["copt_font_size"] = 26,
    ["copt_line_spacing"] = 110,
}
