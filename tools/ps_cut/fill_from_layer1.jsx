// fill_from_layer1.jsx —— 把当前选区内的像素从「图层 1」补到当前图层
//
// 用法：
//   1. 在需要补的图层上，用套索/魔棒把缺失区域选出来
//   2. Photoshop 菜单：文件 > 脚本 > 浏览…  选择本文件
//   3. 脚本会把「图层 1」中该选区内的像素贴入当前图层，并向下合并
//
// 注意：画布尺寸相同 ⇒ 位置按原坐标对齐，不会错位。
//      运行一次 = 一步历史记录，Ctrl+Z 可撤销。

#target photoshop

(function () {
    var doc = app.activeDocument;

    if (!doc.selection) {
        alert("请先在要修补的图层上做一个选区（圈出缺失区域），再运行本脚本。");
        return;
    }

    // 取源图层：优先叫「图层 1」，否则退回到最底层
    var src = null;
    try {
        src = doc.layers.getByName("图层 1");
    } catch (e) {
        src = doc.layers[doc.layers.length - 1];
    }

    var target = doc.activeLayer;
    if (src === target) {
        alert("当前图层就是源图层「" + src.name + "」，请切换到需要补的图层再运行。");
        return;
    }

    var sel = doc.selection;

    // 在选区范围内从源图层复制
    doc.activeLayer = src;
    sel.copy();

    // 贴入当前图层并合并
    doc.activeLayer = target;
    doc.pasteInto();
    doc.activeLayer.merge();
    sel.deselect();

    // 收尾
    app.activeDocument.activeLayer = target;
})();
