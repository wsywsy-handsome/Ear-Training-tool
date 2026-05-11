# Ear Training

一个基于 MIDI 的和弦听辨练习工具。程序会随机选择一个根音和和弦 pattern，先从 MIDI 输出端口播放和弦，然后监听 MIDI 键盘输入，并判断你弹出的 pitch classes 是否正确。

## 安装

依赖已经安装到 `et` 环境。之后如果要重建环境：

```bash
conda activate et
python -m pip install -e .
```

## 查看 MIDI 端口

```bash
conda run --no-capture-output -n et ear-training list-ports
```

## 开始练习

```bash
conda run --no-capture-output -n et ear-training drill --input "你的 MIDI 键盘端口" --output "你的 MIDI 输出端口"
```

## 可视化练习

```bash
conda run --no-capture-output -n et ear-training gui \
  --input "你的 MIDI 键盘端口" \
  --output "你的 MIDI 输出端口" \
  --chords major minor dominant7 major7 minor7 sus4 add9 \
  --root-range C3:C5 \
  --keyboard-range C4:B5 \
  --forever
```

窗口里的虚拟键盘默认只显示两个八度，并按音名显示你在 MIDI 键盘上按下的音。答对后会高亮本道题答案，并在短暂停留后进入下一题。界面提供“重听”和“显示答案”；如果提前显示答案，本题不会计入首次答对。

常用参数：

```bash
conda run --no-capture-output -n et ear-training drill \
  --config config/chords.yaml \
  --chords major minor dominant7 major7 minor7 sus4 add9 \
  --root-range C3:C5 \
  --rounds 20 \
  --answer-window 8
```

一直练到按 Ctrl-C，并且每道题必须答对才进入下一题：

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

如果不指定 `--input` 或 `--output`，`mido` 会尝试打开系统默认端口。输入默认监听所有 MIDI channel；输出默认使用 channel 1，可以用 `--input-channel` 和 `--output-channel` 改。macOS 上通常需要一个软件音源或 IAC/DAW 来接收 MIDI 输出。

如果只是想确认键盘输入是否能被程序收到：

```bash
conda run --no-capture-output -n et ear-training monitor --input "你的 MIDI 键盘端口"
```

## 自定义和弦

编辑 `config/chords.yaml`：

```yaml
chords:
  major:
    label: Major
    intervals: [0, 4, 7]
    group: triads
```

`intervals` 是相对根音的半音数。比如属九和弦可以写成 `[0, 4, 7, 10, 14]`。
