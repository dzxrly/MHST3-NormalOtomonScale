local coreApi  = require("NormalOtomonScale.utils")
local config   = require("NormalOtomonScale.config")
local i18n     = require("NormalOtomonScale.i18n")

local M        = {}

local settings = {
    lockField  = false,
    lockBattle = false,
}

local function loadSettings()
    local data = json.load_file(config.SETTINGS_PATH)
    if data == nil then return end
    if data.lockField ~= nil then settings.lockField = data.lockField end
    if data.lockBattle ~= nil then settings.lockBattle = data.lockBattle end
end

local function saveSettings()
    json.dump_file(config.SETTINGS_PATH, settings)
end

-- Hook 1: lock field otomon scale
sdk.hook(
    sdk.find_type_definition("app.WorldOtomonCharacter"):get_method("onSystemSetupFinished()"),
    function(args)
        thread.get_hook_storage()["this"] = sdk.to_managed_object(args[2])
    end,
    function(retval)
        if not settings.lockField then return retval end
        local this = thread.get_hook_storage()["this"]
        if this == nil then return retval end
        local gameObj = this:get_GameObject()
        if gameObj == nil then return retval end
        local transform = gameObj:get_Transform()
        if transform == nil then return retval end
        local s = config.FORCED_SCALE
        transform:call("set_LocalScale(via.vec3)", Vector3f.new(s, s, s))
        return retval
    end
)

-- Hook 2: lock battle otomon scale
sdk.hook(
    sdk.find_type_definition("app.BattleOtomonCharacter"):get_method("getParamHolder()"),
    function(args)
        thread.get_hook_storage()["this"] = sdk.to_managed_object(args[2])
    end,
    function(retval)
        if not settings.lockBattle then return retval end
        local this = thread.get_hook_storage()["this"]
        if this == nil then return retval end
        local s = config.FORCED_SCALE
        this:call("setLocalScale(via.vec3)", Vector3f.new(s, s, s))
        return retval
    end
)

function M.drawUI()
    imgui.text_colored("1. " .. i18n.getUIText("camp_tip_1"), config.TIPS_COLOR)
    imgui.text_colored("   " .. i18n.getUIText("camp_tip_2"), config.TIPS_COLOR)
    imgui.text_colored("2. " .. i18n.getUIText("large_otomon_tip_1"), config.TIPS_COLOR)
    imgui.text_colored("   " .. i18n.getUIText("large_otomon_tip_2"), config.TIPS_COLOR)

    local changed, newVal

    changed, newVal = imgui.checkbox(i18n.getUIText("lock_field_otomon"), settings.lockField)
    if changed then
        settings.lockField = newVal
        saveSettings()
    end

    changed, newVal = imgui.checkbox(i18n.getUIText("lock_battle_otomon"), settings.lockBattle)
    if changed then
        settings.lockBattle = newVal
        saveSettings()
    end
end

function M.modInit()
    coreApi.log("Initializing...")
    i18n.initLanguage()
    coreApi.log("Language Index: " .. tostring(i18n.languageIdx))
    loadSettings()
    coreApi.log("Initialization complete")
end

return M
