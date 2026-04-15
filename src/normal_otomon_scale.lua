--- Normal Monsties Size
--- Author: Egg Targaryen
--- For Monster Hunter Stories 3
local coreApi    = require("NormalOtomonScale.utils")
local mod        = require("NormalOtomonScale.init")

-- DO NOT CHANGE THE NEXT LINE, ONLY UPDATE THE VERSION NUMBER
local modVersion = "v1.0.1"
-- DO NOT CHANGE THE PREVIOUS LINE

coreApi.init("NormalOtomonScale")

re.on_draw_ui(function()
    if imgui.tree_node("Normal Monsties Size") then
        imgui.text("VERSION: " .. modVersion .. " | by Egg Targaryen")
        mod.drawUI()
        imgui.tree_pop()
    end
end)
