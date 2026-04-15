--- Language Index:
--- 0: Japanese
--- 1: English
--- 11: Korean
--- 12: Chinese (Traditional)
--- 13: Chinese (Simplified)
local coreApi = require("NormalOtomonScale.utils")

local M = coreApi.createI18n({
    defaultLanguageIdx = 1,
    text = {
        [0] = {
            lock_field_otomon  = "フィールドのオトモンサイズを固定する",
            lock_battle_otomon = "戦闘時のオトモンサイズを固定する",
            -- tip 1: camp
            camp_tip_1         = "設定後は、キャンプに出入りして",
            camp_tip_2         = "MODを有効にしてください。",
            -- tip 2: large otomon
            large_otomon_tip_1 = "体が大きすぎるオトモンに乗りたい場合は、",
            large_otomon_tip_2 = "まずジャンプしてから召喚してください。",
        },
        [1] = {
            lock_field_otomon  = "Lock Field Monsties Size",
            lock_battle_otomon = "Lock Battle Monsties Size",
            -- tip 1: camp
            camp_tip_1         = "After setting, enter/exit a Camp",
            camp_tip_2         = "to apply the mod.",
            -- tip 2: large otomon
            large_otomon_tip_1 = "For oversized Monsties, you may need to",
            large_otomon_tip_2 = "jump first, then summon for riding.",
        },
        [11] = {
            lock_field_otomon  = "필드 동료몬 크기 고정",
            lock_battle_otomon = "전투 중 동료몬 크기 고정",
            -- tip 1: camp
            camp_tip_1         = "설정 후, 캠프에 드나들어",
            camp_tip_2         = "MOD를 적용하세요.",
            -- tip 2: large otomon
            large_otomon_tip_1 = "체형이 너무 큰 동료몬에 탑승하려면,",
            large_otomon_tip_2 = "먼저 점프한 후 소환하세요.",
        },
        [12] = {
            lock_field_otomon  = "鎖定 Field 隨行獸尺寸",
            lock_battle_otomon = "鎖定戰鬥時的隨行獸尺寸",
            -- tip 1: camp
            camp_tip_1         = "設定完成後，請進出營地",
            camp_tip_2         = "使 MOD 生效。",
            -- tip 2: large otomon
            large_otomon_tip_1 = "體型過大的隨行獸，",
            large_otomon_tip_2 = "可能需要先跳躍再召喚騎乘。",
        },
        [13] = {
            lock_field_otomon  = "锁定 Field 随行兽尺寸",
            lock_battle_otomon = "锁定战斗时的随行兽尺寸",
            -- tip 1: camp
            camp_tip_1         = "设置完成后，请进出营地",
            camp_tip_2         = "使 MOD 生效。",
            -- tip 2: large otomon
            large_otomon_tip_1 = "对于体积过大的随行兽，",
            large_otomon_tip_2 = "可能需要先跳跃再召唤骑乘。",
        },
    }
})

return M
