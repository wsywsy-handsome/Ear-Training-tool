# Ear Training

一个基于 MIDI 的和弦听辨练习工具。它会随机播放一个音或和弦，监听 MIDI 键盘输入，并按 pitch class 判断答案是否正确，所以转位、不同八度和重复音都不会影响判题。

项目目前提供两种练习方式：

- `gui`：带虚拟键盘的可视化练习界面，推荐日常使用。
- `drill`：纯命令行练习模式，适合快速测试或无 GUI 环境。

## Features

- MIDI 输入监听：使用真实 MIDI 键盘作答。
- MIDI 输出播放：把题目发送到软件音源、DAW、IAC Bus 或硬件音源。
- 可视化键盘：实时显示你按下的音，答对后高亮本道题答案。
- GUI 和弦选择器：按组或按单个和弦选择练习范围。
- 配置持久化：GUI 选择会保存到 `config/gui_settings.yaml`，下次启动继续使用。
- 自定义和弦：在 YAML 中定义任意 interval pattern。
- 练习模式：支持有限轮数，也支持一直练到关闭窗口或按 `Ctrl-C`。
- 宽容判题：按音名集合判断，不区分八度和转位。

## Requirements

- Python 3.10+
- conda 环境：本文示例使用 `et`
- 一个 MIDI 输入设备，例如 MIDI 键盘
- 一个 MIDI 输出目标，例如：
  - DAW / 软件音源
  - macOS IAC Driver + GarageBand / Logic / Ableton 等
  - 外部硬件音源

> 注意：很多 MIDI 键盘只是控制器，本身不发声。`--input` 通常指向 MIDI 键盘，`--output` 应该指向能把 MIDI 变成声音的音源。

## Installation

如果你已经在当前项目里配置过 `et` 环境，可以直接使用。

重新安装依赖和命令入口：

```bash
conda activate et
python -m pip install -e .
```

项目依赖定义在 [pyproject.toml](pyproject.toml)：

- `mido`
- `python-rtmidi`
- `PyYAML`

## Quick Start

先列出当前系统可用的 MIDI 端口：

```bash
conda run --no-capture-output -n et ear-training list-ports
```

你会看到类似：

```text
MIDI inputs:
  1. Your MIDI Keyboard

MIDI outputs:
  1. IAC Driver Bus 1
```

启动 GUI：

```bash
conda run --no-capture-output -n et ear-training gui \
  --input "Your MIDI Keyboard" \
  --output "IAC Driver Bus 1" \
  --root-range C3:C5 \
  --keyboard-range C4:B5 \
  --forever
```

如果你已经根据自己的设备改好了 [run.sh](run.sh)，也可以直接：

```bash
sh run.sh
```

## GUI Mode

GUI 是推荐模式：

```bash
conda run --no-capture-output -n et ear-training gui \
  --input "你的 MIDI 键盘端口" \
  --output "你的 MIDI 输出端口" \
  --root-range C3:C5 \
  --keyboard-range C4:B5 \
  --forever
```

界面包含：

- 虚拟键盘：默认显示两个八度，按音名显示你的输入。
- 重听：重新播放当前题目。
- 显示答案：高亮本道题正确音名。
- 结束训练：停止当前练习并生成诊断报告。
- 和弦选择器：在右侧按组或单个和弦勾选练习范围。
- 自动保存：GUI 选择会写入 `config/gui_settings.yaml`。

在 `--forever` 模式中，你可以随时修改右侧和弦选择；当前题不变，后续题目会使用新的选择。

点击“结束训练”后，GUI 会生成一份报告：

- 总体完成题数、首次答对率、非首次答对数量、手动显示答案数量
- 按和弦类型分析薄弱项
- 按根音分析薄弱项
- 优先关注列表，方便下一轮集中练习

报告中的“薄弱题”定义为：没有首次答对，或本题中手动点击过“显示答案”。点击结束时正在进行但尚未完成的题目不会纳入统计。

常用 GUI 参数：

```text
--input             MIDI 输入端口
--output            MIDI 输出端口
--root-range        出题根音范围，例如 C3:C5
--keyboard-range    虚拟键盘显示范围，例如 C4:B5
--forever           一直练到关闭窗口
--rounds            不使用 --forever 时的题目数量
--next-delay        答对后显示答案多久再进入下一题
--settings          GUI 选择配置保存路径
```

## CLI Drill Mode

命令行模式适合轻量练习或调试：

```bash
conda run --no-capture-output -n et ear-training drill \
  --input "你的 MIDI 键盘端口" \
  --output "你的 MIDI 输出端口" \
  --chords major minor dominant7 major7 minor7 sus4 add9 \
  --root-range C3:C5 \
  --rounds 20 \
  --show-answer
```

一直练到按 `Ctrl-C`，并且每道题必须答对才进入下一题：

```bash
conda run --no-capture-output -n et ear-training drill \
  --input "你的 MIDI 键盘端口" \
  --output "你的 MIDI 输出端口" \
  --chords major minor dominant7 major7 minor7 sus4 add9 \
  --root-range C3:C5 \
  --forever \
  --require-correct \
  --show-answer
```

## MIDI Setup Notes

### MIDI Keyboard Does Not Make Sound

如果你的 MIDI 键盘只是控制器，把 `--output` 设成键盘本身通常不会有声音。你需要一个能发声的目标：

```text
ear-training -> MIDI output -> 软件音源 / DAW -> 扬声器
MIDI keyboard -> MIDI input -> ear-training
```

### macOS IAC Driver

macOS 可以用 IAC Bus 把程序输出接到 DAW 或软件音源：

1. 打开 `Audio MIDI Setup`
2. 菜单选择 `Window -> Show MIDI Studio`
3. 打开 `IAC Driver`
4. 勾选 `Device is online`
5. 创建或启用一个 bus，例如 `IAC Driver Bus 1`
6. 在 DAW / 软件音源中监听这个 bus
7. 把 `ear-training --output` 设置为这个 bus

## Monitor MIDI Input

如果不确定键盘输入是否被程序收到，可以使用 monitor：

```bash
conda run --no-capture-output -n et ear-training monitor \
  --input "你的 MIDI 键盘端口"
```

按键后应该能看到：

```text
note_on  note= 60 velocity= 80
note_off note= 60 velocity=  0
```

## Chord Configuration

和弦定义在 [ear_training/chords.yaml](ear_training/chords.yaml)。每个和弦包含：

- `label`：界面显示名称
- `intervals`：相对根音的半音数
- `group`：GUI 右侧分组

示例：

```yaml
chords:
  major:
    label: Major
    intervals: [0, 4, 7]
    group: triads
  dominant9:
    label: Dominant 9
    intervals: [0, 4, 7, 10, 14]
    group: ninths
```

内置分组包括：

- `single`：单音
- `triads`：三和弦
- `suspended`：挂留和弦
- `sevenths`：七和弦
- `ninths`：九和弦

你也可以添加新的 `group`。GUI 会自动把未知分组显示为一个新的分组。

## Project Layout

```text
ear_training/
  cli.py          # 命令行入口和子命令
  gui.py          # Tkinter GUI
  midi_io.py      # MIDI 输入/输出工具
  music.py        # 音名、和弦、判题逻辑
  config.py       # YAML 配置加载
  chords.yaml     # 默认和弦配置
config/
  gui_settings.yaml  # GUI 自动生成的选择状态
tests/
  test_music.py
run.sh
pyproject.toml
```

## Development

运行测试：

```bash
conda run -n et python -m unittest discover -s tests
```

检查 Python 文件是否能编译：

```bash
conda run -n et python -m compileall ear_training
```

查看所有命令：

```bash
conda run -n et ear-training --help
conda run -n et ear-training gui --help
conda run -n et ear-training drill --help
```

## Troubleshooting

### 程序看起来没有输出

交互程序建议使用：

```bash
conda run --no-capture-output -n et ...
```

否则 `conda run` 可能会缓存输出，看起来像卡住。

### 没有声音

确认 `--output` 指向的是软件音源、DAW、IAC Bus 或硬件音源，而不是只负责输入的 MIDI 控制器。

### GUI 中没有出现某些和弦

确认 [ear_training/chords.yaml](ear_training/chords.yaml) 中的 YAML 格式正确，并且每个和弦都包含 `intervals` 和 `group`。

### 选项太多看不完

GUI 右侧配置区支持滚动。把鼠标移到右侧和弦选择区域后，可以用滚轮上下滚动。
