// Copyright (c) 2018 Ultimaker B.V.
// Cura is released under the terms of the LGPLv3 or higher.

import QtQuick 2.10
import QtQuick.Controls 2.3
import QtQuick.Layouts 1.3

import UM 1.5 as UM
import Cura 1.6 as Cura

RowLayout
{
    // Constrain the RowLayout to the Loader's width so it never overflows into the caret button.
    width: parent.width
    spacing: 0

    readonly property var tipColorMap: ({
        "Nordson Olive 1.54mm ID": "#808000",
        "Nordson Amber 1.36mm ID": "#FFBF00",
        "Nordson Green 0.84mm ID": "#00A550",
        "Nordson Pink 0.61mm ID": "#FF69B4",
        "Nordson Purple 0.51mm ID": "#800080",
        "Nordson Blue 0.41mm ID": "#0057A8",
        "Nordson Orange 0.33mm ID": "#FF8C00",
        "Nordson Red 0.25mm ID": "#CC0000",
        "Nordson Clear 0.20mm ID": "#FFFFFF",
        "Nordson Lavender 0.15mm ID": "#B57EDC",
        "Nordson Yellow 0.10mm ID": "#FFD700"
    })

    function getCustomTipColor(name)
    {
        var raw = UM.Preferences.getValue("printess/tip_colors")
        if (!raw) return ""
        try { return JSON.parse(raw)[name] || "" } catch(e) { return "" }
    }

    // ── Left group: Dispense Tip ──────────────────────────────────────────────

    UM.Label
    {
        text: catalog.i18nc("@label", "Dispense Tip")
        font: UM.Theme.getFont("medium")
        color: UM.Theme.getColor("text_medium")
        wrapMode: Text.NoWrap
        Layout.rightMargin: UM.Theme.getSize("narrow_margin").width
    }

    UM.Label
    {
        text: "·"
        font: UM.Theme.getFont("medium")
        color: UM.Theme.getColor("text_medium")
        Layout.rightMargin: UM.Theme.getSize("narrow_margin").width
    }

    // Profile name — fills all middle space; elides if the panel is narrow.
    UM.Label
    {
        id: profileNameLabel
        text: Cura.MachineManager.activeQualityOrQualityChangesName
        font: UM.Theme.getFont("medium")
        wrapMode: Text.NoWrap
        elide: Text.ElideRight
        Layout.fillWidth: true
        Layout.minimumWidth: 0
    }

    Rectangle
    {
        property string activeName: Cura.MachineManager.activeQualityOrQualityChangesName
        property string resolvedColor:
        {
            var c = tipColorMap[activeName]
            if (c !== undefined) return c
            return getCustomTipColor(activeName)
        }
        visible: resolvedColor !== "" && activeName !== ""
        width: visible ? Math.round(height * 1.6) : 0
        height: Math.round(UM.Theme.getFont("medium").pixelSize * 0.85)
        radius: height / 2
        color: resolvedColor !== "" ? resolvedColor : "transparent"
        border.width: resolvedColor === "#FFFFFF" ? 1 : 0
        border.color: "#888888"
        Layout.alignment: Qt.AlignVCenter
        Layout.leftMargin: UM.Theme.getSize("narrow_margin").width
    }

    // ── Right group: Layer Height ─────────────────────────────────────────────

    UM.SettingPropertyProvider
    {
        id: headerLayerHeight
        containerStack: Cura.MachineManager.activeMachine
        key: "layer_height"
        watchedProperties: ["value"]
    }

    UM.Label
    {
        text: catalog.i18nc("@label", "Layer Height")
        font: UM.Theme.getFont("medium")
        color: UM.Theme.getColor("text_medium")
        wrapMode: Text.NoWrap
        Layout.leftMargin: UM.Theme.getSize("default_margin").width
        Layout.rightMargin: UM.Theme.getSize("narrow_margin").width
    }

    UM.Label
    {
        text: "·"
        font: UM.Theme.getFont("medium")
        color: UM.Theme.getColor("text_medium")
        Layout.rightMargin: UM.Theme.getSize("narrow_margin").width
    }

    UM.Label
    {
        text: headerLayerHeight.properties.value !== undefined
            ? parseFloat(headerLayerHeight.properties.value).toFixed(2) + " mm"
            : ""
        font: UM.Theme.getFont("medium_bold")
        wrapMode: Text.NoWrap
    }
}
