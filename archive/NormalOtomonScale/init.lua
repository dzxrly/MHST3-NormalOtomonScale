local coreApi  = require("NormalOtomonScale.utils")
local config   = require("NormalOtomonScale.config")
local i18n     = require("NormalOtomonScale.i18n")

local M        = {}

local settings = {
    lockField       = false,
    lockBattle      = false,
    applyEnemyScale = false,
}

local function loadSettings()
    local data = json.load_file(config.SETTINGS_PATH)
    if data == nil then return end
    if data.lockField ~= nil then settings.lockField = data.lockField end
    if data.lockBattle ~= nil then settings.lockBattle = data.lockBattle end
    if data.applyEnemyScale ~= nil then settings.applyEnemyScale = data.applyEnemyScale end
end

local function saveSettings()
    json.dump_file(config.SETTINGS_PATH, settings)
end

-- load settings immediately so hooks have correct values from the start
loadSettings()

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

        local otomonContext = this:get_Context()
        local otomonId = nil
        if otomonContext ~= nil then
            otomonId = tonumber(otomonContext:get_field("<OtomonID>k__BackingField"))
        end

        local gameObj = this:get_GameObject()
        if gameObj == nil then return retval end

        local transform = gameObj:get_Transform()
        if transform == nil then return retval end

        local s = config.FORCED_SCALE
        if settings.applyEnemyScale and otomonId ~= nil and config.ENEMY_BODY_SCALE and config.ENEMY_BODY_SCALE[otomonId] then
            s = s + (config.ENEMY_BODY_SCALE[otomonId] - 1.0)
        end
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

        local otomonId = tonumber(this:get_field("_OtID"))

        local s = config.FORCED_SCALE
        if settings.applyEnemyScale and otomonId ~= nil and config.ENEMY_BODY_SCALE and config.ENEMY_BODY_SCALE[otomonId] then
            s = s + (config.ENEMY_BODY_SCALE[otomonId] - 1.0)
        end
        this:call("setLocalScale(via.vec3)", Vector3f.new(s, s, s))
        return retval
    end
)

function M.drawUI()
    i18n.initLanguage()

    imgui.text_colored("1. " .. i18n.getUIText("camp_tip_1"), config.TIPS_COLOR)
    imgui.text_colored("   " .. i18n.getUIText("camp_tip_2"), config.TIPS_COLOR)
    imgui.text_colored("2. " .. i18n.getUIText("large_otomon_tip_1"), config.TIPS_COLOR)
    imgui.text_colored("   " .. i18n.getUIText("large_otomon_tip_2"), config.TIPS_COLOR)
    imgui.new_line()

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

    changed, newVal = imgui.checkbox(i18n.getUIText("apply_enemy_scale"), settings.applyEnemyScale)
    if changed then
        settings.applyEnemyScale = newVal
        saveSettings()
    end
end

function M.modInit()
    coreApi.log("Initializing...")
    coreApi.log("Initialization complete")
end

return M
