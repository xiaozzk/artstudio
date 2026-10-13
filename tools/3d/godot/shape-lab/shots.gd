extends RefCounted
## 出图流水线（`run.cmd --shots`）：
##   * 6 角色 × 3 档（thin k=-1 / standard k=0 / heavy k=+1）各 1 张单图（舞台固定 960x900）
##   * 每角色 1 张「三档并排」联系表
##   * 1 张交互页整页图（1500x900 离屏视口：左舞台 + 右中文面板）
## 全部写**绝对路径**到 <缓存根>/shots/；返回进程退出码（有角色加载失败 → 3）。
##
## 注意：`app` 故意不加静态类型（main.gd 的方法在静态类型下解析不到），
## 且 Godot 的 `--headless` 是 dummy 渲染器**出不了图**（实测 texture_2d_get 报 null），
## 所以截图模式必须开真窗口（run.cmd 用小分辨率窗口，成图尺寸由离屏视口决定）。

const STAGE = preload("res://stage.gd")
const CACHE = preload("res://cache.gd")

const TIERS := [["thin", -1.0], ["standard", 0.0], ["heavy", 1.0]]
const PAGE_W := 1500
const PAGE_H := 900
const SHEET_CELL_W := 640
const PAGE_K := 0.6

static func run(app) -> int:
	var out_dir: String = CACHE.shots_dir()
	var chars: Array = app.cache["chars"]
	var failed := 0
	var shot_paths: Array = []
	for ci in chars.size():
		var c: Dictionary = chars[ci]
		await app.load_character(ci)
		if not (app.avatar["errors"] as Array).is_empty():
			failed += 1
		var imgs: Array = []
		for t in TIERS:
			app.set_state(float(t[1]), 1.0)
			await app.settle(6)
			var img: Image = STAGE.snapshot(app.stage)
			var stats: Dictionary = STAGE.page_stats(img)
			var p := "%s/shape_%s_%s.png" % [out_dir, String(c["id"]), String(t[0])]
			var r: Dictionary = STAGE.save_png_abs(img, p)
			shot_paths.append(p)
			imgs.append(img.duplicate())
			print("SHOT  %s %-8s k=%+.2f  margin=%s  %s" % [String(c["id"]), String(t[0]),
				float(t[1]), JSON.stringify(app.last_fit.get("margin_px", {})), JSON.stringify(r)])
			print("STATS %s %-8s non_bg=%.2f%% colors=%d/%d" % [String(c["id"]), String(t[0]),
				float(stats["non_bg_pct"]), int(stats["colors"]), int(stats["colors_fine"])])
			if float(stats["non_bg_pct"]) < 1.0:
				failed += 1
				print("ERROR 单图疑似空白：%s %s %s" % [String(c["id"]), String(t[0]),
					JSON.stringify(stats)])
			if String(t[0]) == "standard":
				print("READOUT_START %s" % String(c["id"]))
				print(app.readout_text())
				print("READOUT_END %s" % String(c["id"]))
		var sheet := compose_row(imgs, SHEET_CELL_W)
		var sp := "%s/shape_%s_sheet_3tiers.png" % [out_dir, String(c["id"])]
		var sr: Dictionary = STAGE.save_png_abs(sheet, sp)
		shot_paths.append(sp)
		print("SHOT  %s 联系表  %s" % [String(c["id"]), JSON.stringify(sr)])
	# ---- 交互页整页图：把同一份 UI 挂进 1500x900 离屏视口（Controls 在 SubViewport 里正常渲染）
	var page := SubViewport.new()
	page.name = "PageViewport"
	page.size = Vector2i(PAGE_W, PAGE_H)
	page.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	app.add_child(page)
	var pui = app.make_ui(page)          # 先建 UI，再装载角色 → 勾选框才会随角色同步
	await app.load_character(0)
	await app.settle(10)
	app.set_state(PAGE_K, 1.0)
	pui.set_status("整页图（离屏 %dx%d）：左=960x900 舞台，右=中文面板；k=%+.2f" % [PAGE_W, PAGE_H, PAGE_K])
	await app.settle(6)
	var pp := "%s/shape_lab_ui_page.png" % out_dir
	var pimg: Image = page.get_texture().get_image()
	var pstats: Dictionary = STAGE.page_stats(pimg)
	var pr: Dictionary = STAGE.save_png_abs(pimg, pp)
	shot_paths.append(pp)
	print("SHOT  交互页整页图  %s" % JSON.stringify(pr))
	print("UI_LAYOUT ", JSON.stringify(pui.layout_report()))
	print("UI_PAGE_STATS ", JSON.stringify(pstats))
	# 空白守卫：看「面板区/整页的非背景占比」。颜色数只作参考打印 —— 稀疏页（如无 morph 的
	# fixture，或只有 3 件裸模）本来就没几个色阶，用颜色数当门槛会误杀（实测 fixture=385）。
	if float(pstats["right_non_bg_pct"]) < 3.0 or float(pstats["non_bg_pct"]) < 3.0:
		failed += 1
		print("ERROR 交互页整页图疑似空白（非背景 %.2f%%，面板区 %.2f%%）"
			% [float(pstats["non_bg_pct"]), float(pstats["right_non_bg_pct"])])
	print("SHOTS_TOTAL=%d  out_dir=%s  failed_chars=%d" % [shot_paths.size(), out_dir, failed])
	print("SHOTS_PATHS_START")
	for p in shot_paths:
		print(p)
	print("SHOTS_PATHS_END")
	return 0 if failed == 0 else 3

## 三张竖图并排成一张联系表（等比缩到 cell_w 宽，中间留 6 px 缝）。
static func compose_row(imgs: Array, cell_w: int, gap := 6) -> Image:
	var first: Image = imgs[0]
	var cell_h: int = int(round(float(cell_w) * float(first.get_height()) / float(first.get_width())))
	var w: int = cell_w * imgs.size() + gap * (imgs.size() - 1)
	var dst := Image.create(w, cell_h, false, Image.FORMAT_RGBA8)
	dst.fill(Color(0.05, 0.05, 0.07))
	for i in imgs.size():
		var im: Image = (imgs[i] as Image).duplicate()
		im.convert(Image.FORMAT_RGBA8)
		im.resize(cell_w, cell_h, Image.INTERPOLATE_LANCZOS)
		dst.blit_rect(im, Rect2i(0, 0, cell_w, cell_h), Vector2i(i * (cell_w + gap), 0))
	return dst
