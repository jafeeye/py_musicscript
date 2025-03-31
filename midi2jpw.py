#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from optparse import OptionParser
import re
import io
import sys
import math
# 需要安裝 mido: pip install mido
try:
    import mido
except ImportError:
    print("錯誤：需要安裝 'mido' 函式庫才能解析 MIDI 檔案。")
    print("請執行： pip install mido")
    sys.exit(1)

# --- Helper Functions (部分來自之前的腳本) ---

def get_beats_from_ticks(ticks, ticks_per_beat):
    """將 MIDI ticks 轉換為拍數 (假設 quarter note = 1 beat)"""
    if ticks_per_beat is None or ticks_per_beat == 0:
        return 0.0 # 無法計算
    return float(ticks) / ticks_per_beat

def calculate_jpw_modifiers_from_beats(beats):
    """根據拍數反推 JPW 時值修飾符 (_, -, .)"""
    tolerance = 0.01 # 稍微放寬容差以處理 MIDI 計時誤差
    # 映射表：拍數 -> (底線數量, 連字號數量, 是否有附點)
    dur_map = {
        4.0: (0, 3, False), 3.0: (0, 2, False), 2.0: (0, 1, False),
        1.5: (0, 0, True),  1.0: (0, 0, False), 0.75: (1, 0, True),
        0.5: (1, 0, False), 0.375:(2, 0, True), 0.25: (2, 0, False),
        0.1875:(3, 0, True),0.125:(3, 0, False)
    }
    for b, mods in dur_map.items():
        if abs(beats - b) < tolerance:
            return mods

    # 嘗試近似處理更長或不規則的時值
    if beats > 4.0 and abs(beats % 1.0) < tolerance: # 嘗試處理 >4 拍的整數拍
        hyphens = int(round(beats)) - 1
        if hyphens >= 3: return (0, hyphens, False) # e.g., 5 beats -> 0, 4, False

    print(f"警告：無法精確映射拍數={beats} 到 JPW 時值修飾符。使用預設值 (基礎音符)。")
    return (0, 0, False) # 預設返回基礎時值 (通常是四分音符)

# 音階和 MIDI 編號的映射 (C大調/a小調)
# C4 = 60, C#4 = 61, D4 = 62 ... B4 = 71, C5 = 72
SCALE_CMAJ = {0: '1', 2: '2', 4: '3', 5: '4', 7: '5', 9: '6', 11: '7'} # 相對於 C 的音程 -> JPW 數字

def midi_note_to_jpw_simple(midi_note_num):
    """簡化版：將 MIDI 音高數字轉換為 JPW 數字和八度標記 (基於 C 大調)"""
    if not (0 <= midi_note_num <= 127):
        return ('1', 0, '') # 無效音高返回預設

    octave = midi_note_num // 12
    note_in_octave = midi_note_num % 12

    # 基礎數字映射 (C 大調)
    jpw_num = SCALE_CMAJ.get(note_in_octave)
    jpw_prefix = ''
    if jpw_num is None:
        # 可能是升降音，找相鄰的音
        if note_in_octave - 1 in SCALE_CMAJ:
            jpw_num = SCALE_CMAJ[note_in_octave - 1]
            jpw_prefix = '#' # 升號
        elif note_in_octave + 1 in SCALE_CMAJ:
            jpw_num = SCALE_CMAJ[note_in_octave + 1]
            jpw_prefix = 'b' # 降號
        else:
             jpw_num = '1' # 非常規音符，預設為 1

    # 八度轉換 (假設 C4 / MIDI 60 所在的八度對應 JPW 無標記，即 oct_mod = 0)
    # MIDI C4 = 60 => octave 5 (從0開始算)
    # Lilypond c' = JPW base (mod 0)
    # C4(60)=c', C5(72)=c'', C3(48)=c
    reference_octave = 5 # C4 = MIDI octave 5
    jpw_octave_mod = octave - reference_octave

    return (jpw_num, jpw_octave_mod, jpw_prefix)


# --- MidiToJpw Class ---

class MidiToJpw:
    def __init__(self):
        self.title = ""
        self.key_signature = 'C' # MIDI 調號 (預設 C)
        self.key_mode = 0 # 0=major, 1=minor
        self.jpw_key_str = "1=C" # JPW 調號字串
        self.time_sig_num = 4
        self.time_sig_den = 4
        self.jpw_time_sig = "4/4"
        self.tempo_microseconds = 500000 # microseconds per quarter note (預設 120 BPM)
        self.jpw_tempo_str = "J=120"
        self.ticks_per_beat = 480 # MIDI Ticks per Beat (常用預設值)
        self.jpw_voice_tokens = [] # 儲存轉換後的 JPW 音符/符號

    def parse(self, midi_file_path):
        """解析 MIDI 檔案並提取資訊"""
        try:
            mid = mido.MidiFile(midi_file_path)
            print(f"成功讀取 MIDI 檔案: '{midi_file_path}'")
        except Exception as e:
            print(f"錯誤：無法讀取或解析 MIDI 檔案 '{midi_file_path}': {e}")
            return False

        if mid.ticks_per_beat:
            self.ticks_per_beat = mid.ticks_per_beat
            print(f"  Ticks per beat: {self.ticks_per_beat}")
        else:
             print(f"警告：MIDI 檔案未指定 ticks_per_beat，使用預設值 {self.ticks_per_beat}")

        notes_in_track = [] # 儲存 (音高, 開始時間 tick, 結束時間 tick)
        current_time_ticks = 0
        last_event_time_ticks = 0
        track_found = False

        # 通常音軌 0 是元數據，音軌 1 或之後包含音符
        for i, track in enumerate(mid.tracks):
            print(f"處理音軌 {i}: {track.name}")
            playing_notes = {} # {note_num: start_tick}
            current_time_ticks = 0 # 每條音軌時間獨立

            # 第一次遍歷，獲取元數據和音符事件時間
            temp_notes = []
            has_notes_in_this_track = False
            for msg in track:
                current_time_ticks += msg.time # 累加 delta time

                if msg.is_meta:
                    if msg.type == 'track_name' and not self.title:
                        self.title = msg.name
                        print(f"  找到標題: {self.title}")
                    elif msg.type == 'set_tempo':
                        self.tempo_microseconds = msg.tempo
                        bpm = mido.tempo2bpm(msg.tempo)
                        self.jpw_tempo_str = f"J={int(round(bpm))}"
                        print(f"  找到速度: {self.jpw_tempo_str} ({msg.tempo} us/beat)")
                    elif msg.type == 'time_signature':
                        self.time_sig_num = msg.numerator
                        self.time_sig_den = msg.denominator
                        # MIDI denominator 是 2 的次方 (2=quarter, 3=eighth)
                        actual_den = 2**msg.denominator
                        self.jpw_time_sig = f"{self.time_sig_num}/{actual_den}"
                        print(f"  找到拍號: {self.jpw_time_sig}")
                        # Lilypond ticks_per_beat *might* relate to denominator, but usually fixed per file.
                    elif msg.type == 'key_signature':
                        self.key_signature = msg.key # e.g., 'C', 'Gm', 'F#m'
                        # 嘗試轉換為 JPW 格式
                        match = re.match(r"([A-G])([#b])?m?", self.key_signature)
                        if match:
                             base = match.group(1)
                             acc = match.group(2) if match.group(2) else ''
                             mode_num = '6' if 'm' in self.key_signature else '1'
                             jpw_key = acc.replace('b','b').replace('#','#') + base # e.g., bE, #F
                             self.jpw_key_str = f"{mode_num}={jpw_key}"
                        print(f"  找到調號: {self.key_signature} -> JPW: {self.jpw_key_str}")

                elif msg.type == 'note_on' and msg.velocity > 0:
                    has_notes_in_this_track = True
                    playing_notes[msg.note] = current_time_ticks
                elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                    if msg.note in playing_notes:
                        start_tick = playing_notes.pop(msg.note)
                        end_tick = current_time_ticks
                        # 儲存音符資訊 (音高, 開始, 結束)
                        temp_notes.append({'pitch': msg.note, 'start': start_tick, 'end': end_tick})

            # 如果當前音軌包含音符且我們還沒選擇音軌，則使用此音軌
            if has_notes_in_this_track and not track_found:
                 print(f"  --> 選定音軌 {i} 進行轉換。")
                 # 按開始時間排序音符
                 notes_in_track = sorted(temp_notes, key=lambda x: x['start'])
                 track_found = True
                 # 只處理第一個找到音符的音軌，然後跳出
                 break
            elif not track_found and i == len(mid.tracks) - 1: # 如果到最後一軌還沒找到音符
                 print("警告：在所有音軌中均未找到有效的音符事件。無法產生 JPW 聲音。")


        # --- 第二步：根據排序後的音符和時間生成 JPW tokens ---
        last_note_end_tick = 0
        for note in notes_in_track:
            start_tick = note['start']
            end_tick = note['end']
            pitch = note['pitch']
            duration_ticks = end_tick - start_tick

            # 1. 檢查是否有休止符
            rest_ticks = start_tick - last_note_end_tick
            if rest_ticks > self.ticks_per_beat * 0.05: # 只有顯著的間隔才算休止符 (忽略小誤差)
                rest_beats = get_beats_from_ticks(rest_ticks, self.ticks_per_beat)
                u_count, h_count, dot = calculate_jpw_modifiers_from_beats(rest_beats)
                rest_token = "0" # JPW 休止符
                rest_token += "_" * u_count + "-" * h_count
                if dot: rest_token += "."
                self.jpw_voice_tokens.append(rest_token)
                print(f"  - 插入休止符: tick={last_note_end_tick}-{start_tick}, beats={rest_beats:.2f}, token={rest_token}")


            # 2. 處理當前音符
            if duration_ticks <= 0: # 忽略零時值音符
                print(f"  - 忽略零時值音符: pitch={pitch}, start={start_tick}")
                continue

            note_beats = get_beats_from_ticks(duration_ticks, self.ticks_per_beat)
            u_count, h_count, dot = calculate_jpw_modifiers_from_beats(note_beats)
            # 使用簡化版音高轉換
            num, oct_mod, prefix = midi_note_to_jpw_simple(pitch)

            if num:
                jpw_token = prefix + num
                if oct_mod > 0: jpw_token += "'" * oct_mod
                elif oct_mod < 0: jpw_token += "," * abs(oct_mod)
                jpw_token += "_" * u_count + "-" * h_count
                if dot: jpw_token += "."
                self.jpw_voice_tokens.append(jpw_token)
                print(f"  - 添加音符: pitch={pitch}, tick={start_tick}-{end_tick}, beats={note_beats:.2f}, token={jpw_token}")


            last_note_end_tick = end_tick

        if not track_found:
             print("警告：未找到包含音符的音軌，無法產生 .Voice 區段。")

        return True


    def build_jpw_output(self):
        """格式化解析到的資訊為 JPW 字串"""
        output = ["// ************** Generated JPW File from MIDI **************", ""]
        # 省略 .Options, .Fonts
        output.append(".Title")
        if self.title: output.append(f"Title = {{{self.title}}}")
        output.append(f"KeyAndMeters = {{{self.jpw_key_str},{self.jpw_time_sig}}}")
        if self.jpw_tempo_str: output.append(f"Expression = {{{self.jpw_tempo_str}}}")
        output.extend(["", ".Voice"])

        # 基本的聲音 token 格式化，每 8 個 token 嘗試換行
        line = "  "
        token_count = 0
        max_tokens_per_line = 8
        bar_counter = 0 # 簡易小節計數
        beats_in_bar = 0.0
        beats_per_bar = float(self.time_sig_num) # 假設 time_sig_den 是 4

        for token in self.jpw_voice_tokens:
             # 嘗試估算 token 的拍數以插入小節線 (非常粗略)
             current_beats = 1.0 # 預設
             if token.startswith('0'): # 休止符
                 u_count = token.count('_')
                 h_count = token.count('-')
                 dot = '.' in token
                 mods = calculate_jpw_modifiers_from_beats(1.0) # 獲取基礎拍數
                 # 反向估算 (不準確)
                 temp_beats = 1.0 * (0.5 ** u_count) + float(h_count)
                 if dot: temp_beats *= 1.5
                 current_beats = temp_beats
             else: # 音符
                 match = re.match(r"[#b]?([1-7])(['`,]*)([_.-]*)", token)
                 if match:
                     dur_mods = match.group(3)
                     u_count = dur_mods.count('_')
                     h_count = dur_mods.count('-')
                     dot = '.' in dur_mods
                     mods = calculate_jpw_modifiers_from_beats(1.0)
                     temp_beats = 1.0 * (0.5 ** u_count) + float(h_count)
                     if dot: temp_beats *= 1.5
                     current_beats = temp_beats

             line += token + " "
             token_count += 1
             beats_in_bar += current_beats

             # 嘗試插入小節線
             if beats_in_bar >= beats_per_bar - 0.01: # 接近或超過一个小节
                 line += "| "
                 beats_in_bar = 0.0 # 重置拍數計數
                 bar_counter += 1
                 if bar_counter % 4 == 0: # 每 4 小節換行
                     output.append(line.strip())
                     line = "  "
                     token_count = 0
             elif token_count >= max_tokens_per_line: # 或達到 token 上限也換行
                 output.append(line.strip())
                 line = "  "
                 token_count = 0

        if line.strip(): output.append(line.strip())
        # 省略 .Words, .Attachments, .Page
        output.extend(["", "// --- End of Generated Content ---"])
        return "\n".join(output)

# --- Main Execution ---
def convert_midi_to_jpw(from_file, to_file):
    converter = MidiToJpw()
    if not converter.parse(from_file):
        print("錯誤：解析 MIDI 檔案失敗。")
        return
    try:
        jpw_output = converter.build_jpw_output()
        # JPW 常見編碼是 GBK/GB18030，但為了更廣泛兼容性先用 UTF-8
        with io.open(to_file, "w", encoding='utf-8') as f_out:
            f_out.write(jpw_output)
        print(f"轉換完成 (基本): '{from_file}' -> '{to_file}'")
        print("注意：MIDI 轉 JPW 為基本轉換，結果可能需要大量審閱和修改。")
    except Exception as e:
        print(f"錯誤：產生或寫入 JPW 檔案時發生錯誤: {e}")

if __name__ == '__main__':
    parser = OptionParser(usage="usage: %prog -f <input.mid> -t <output.jpw>")
    parser.add_option("-f", "--from", dest="from_file", help="輸入 MIDI 檔案 (.mid)")
    parser.add_option("-t", "--to", dest="to_file", help="輸出 JPW 檔案 (.jpw)")
    (opts, args) = parser.parse_args()
    if not opts.from_file or not opts.to_file:
        parser.error("需要提供輸入 (-f) 和輸出 (-t) 檔案參數。")
    convert_midi_to_jpw(opts.from_file, opts.to_file)