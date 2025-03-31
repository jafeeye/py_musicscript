#! /usr/bin/env python3
# -*- coding: utf-8 -*-
from optparse import OptionParser
import re
import io
import sys
import math

# --- Note Class ---
class Note:
    def __init__(self):
        self.base_note = None
        self.octave = 0
        self.lily_duration = "4"
        self.is_rest = False
        self.slur_start = False
        self.slur_end = False
        self.accent = False
        self.prall = False
        self.special = None # For raw Lilypond commands/bars

    def get_lily_note_name(self):
        """Calculates the absolute Lilypond note name with octave marks."""
        if self.is_rest: return 'r'
        base = self.base_note
        relative_octave = self.octave
        if relative_octave == 0: octave_marks = "'"
        elif relative_octave > 0: octave_marks = "'" * (relative_octave + 1)
        else: octave_marks = "," * abs(relative_octave)
        return base + octave_marks

    def __unicode__(self):
        if self.special: return self.special
        parts = [self.get_lily_note_name(), self.lily_duration]
        if self.accent: parts.append("-\\accent")
        if self.prall: parts.append("-\\prall")
        return "".join(parts)

    def __str__(self):
        return self.__unicode__()

class IllegalFormatException(Exception):
    pass

# --- JPW File Class ---
class JpwFile:
    def __init__(self):
        self.options, self.fonts, self.title, self.voice_lines = [], [], [], []
        self.words, self.attachments, self.page, self.notes = [], [], [], []
        self.key, self.sig, self.song_title, self.tempo = None, None, None, None
        self.alternative_opened = False
        self.alternative_closing_needed = 0 # How many '}' needed at the end for \alternative and \repeat
        self.is_inside_slur = False # Track if parser is between ( and )

    def __unicode__(self):
        # Represents parsed JPW sections (excluding generated notes)
        output = [f".{sec.capitalize()}\n" + "\n".join(getattr(self, sec+'_lines' if sec=='voice' else sec)) + "\n"
                  for sec in ['options', 'fonts', 'title', 'voice', 'words', 'attachments', 'page']]
        return "\n".join(output)

    def __str__(self): return self.__unicode__()

    def parse(self, from_file):
        try:
            input_content = io.open(from_file, 'r', encoding='utf-16').read()
            print(f"Read {from_file} with UTF-16.")
        except UnicodeDecodeError:
            try:
                print("UTF-16 failed, trying GBK...")
                input_content = io.open(from_file, 'r', encoding='gbk').read()
                print(f"Read {from_file} with GBK.")
            except Exception as e2: print(f"Error decoding {from_file}: {e2}"); return None
        except Exception as e_other: print(f"Error reading {from_file}: {e_other}"); return None

        section_map = {
            'options': self.options, 'fonts': self.fonts, 'title': self.title,
            'voice': self.voice_lines, 'words': self.words,
            'attachments': self.attachments, 'page': self.page
        }
        current_section_list = None
        for line in input_content.splitlines():
            line_strip = line.strip()
            if not line_strip or line_strip.startswith('//'): continue
            if line.startswith("."):
                section_name = line[1:].strip().lower()
                current_section_list = section_map.get(section_name)
                continue
            if current_section_list is not None: current_section_list.append(line)
        return True

    def number_to_base_note(self, n_char):
        return {'1':'c', '2':'d', '3':'e', '4':'f', '5':'g', '6':'a', '7':'b', '0':'r'}.get(n_char)

    def calculate_lily_duration_from_jpw(self, u_count, h_count, dot):
        beats = 1.0 * (0.5 ** u_count) + float(h_count)
        if dot: beats *= 1.5
        tolerance = 0.001
        dur_map = {4.0:"1", 3.0:"2.", 2.0:"2", 1.5:"4.", 1.0:"4",
                   0.75:"8.", 0.5:"8", 0.375:"16.", 0.25:"16",
                   0.1875:"32.", 0.125:"32"}
        for b, dur in dur_map.items():
            if abs(beats - b) < tolerance: return dur
        print(f"Warning: Unusual beat count {beats}. Defaulting to '4'.")
        return "4"

    def _finalize_current_note(self, note, u_count, h_count, dot):
        """Helper to finalize note duration and add to list."""
        if note:
            note.lily_duration = self.calculate_lily_duration_from_jpw(u_count, h_count, dot)
            self.notes.append(note)
        return None # Return None to clear current_note

    def parse_voice_char_by_char(self):
        self.notes = []
        current_note = None
        o_mod, u_count, h_count = 0, 0, 0
        dot = False
        in_special = False; special_content = ""
        in_dollar = False
        self.is_inside_slur = False # Reset state

        for line_idx, line in enumerate(self.voice_lines):
            i, line_len = 0, len(line)
            while i < line_len:
                char = line[i]
                try:
                    # --- Formatting/Special Commands ---
                    if char == '$' and i + 1 < line_len and line[i+1] == '(':
                        current_note = self._finalize_current_note(current_note, u_count, h_count, dot)
                        o_mod, u_count, h_count, dot = 0, 0, 0, False; self.is_inside_slur = False # Reset state fully
                        in_dollar = True; i += 1; continue
                    if in_dollar:
                        if char == ')': in_dollar = False
                        i += 1; continue
                    if char == '{':
                        in_special = True; special_content = ""; i += 1; continue
                    if in_special:
                        if char == '}':
                            in_special = False
                            if current_note: # Apply special content if note active
                                if special_content == 'ZhongYin': current_note.accent = True
                                elif special_content == 'BoYin': current_note.prall = True
                        else: special_content += char
                        i += 1; continue

                    # --- Slurs/Groupings ---
                    if char == '(':
                        current_note = self._finalize_current_note(current_note, u_count, h_count, dot)
                        o_mod, u_count, h_count, dot = 0, 0, 0, False
                        self.is_inside_slur = True # Mark start
                        i += 1; continue
                    if char == ')':
                        if self.is_inside_slur: # Only process ')' if a slur was started
                            current_note = self._finalize_current_note(current_note, u_count, h_count, dot)
                            if self.notes and isinstance(self.notes[-1], Note):
                                self.notes[-1].slur_end = True # Mark previous note as end
                            # else: print(f"Warning: Slur end ')' without preceding note L{line_idx+1} C{i+1}") # Less noisy
                            o_mod, u_count, h_count, dot = 0, 0, 0, False
                            self.is_inside_slur = False # Mark end
                        # else: print(f"Warning: Unexpected ')' L{line_idx+1} C{i+1}") # Less noisy
                        i += 1; continue

                    # --- Barlines/Repeats (Check BEFORE digits/modifiers if inside slur) ---
                    is_bar_char = char in '|:['
                    if is_bar_char and self.is_inside_slur:
                        # print(f"Warning: Barline character '{char}' inside slur ignored L{line_idx+1} C{i+1}") # Less noisy
                        i += 1; continue # Skip bar processing inside slur

                    if is_bar_char:
                        current_note = self._finalize_current_note(current_note, u_count, h_count, dot)
                        o_mod, u_count, h_count, dot = 0, 0, 0, False; self.is_inside_slur = False # Bars reset state
                        bar_token, consumed = self.parse_multichar_token(line, i, char); i += consumed
                        bar_output = self.parse_bars(bar_token)
                        if bar_output: self.notes.append(bar_output)
                        i += 1; continue # Advance past the token

                    # --- Note Digits ---
                    if char.isdigit():
                        current_note = self._finalize_current_note(current_note, u_count, h_count, dot) # Finalize previous
                        o_mod, u_count, h_count, dot = 0, 0, 0, False # Reset for new note
                        current_note = Note(); current_note.base_note = self.number_to_base_note(char)
                        if current_note.base_note is None: print(f"Error: Unknown digit '{char}'"); current_note = None; i += 1; continue
                        if current_note.base_note == 'r': current_note.is_rest = True
                        if self.is_inside_slur: current_note.slur_start = True # Apply if inside slur

                    # --- Modifiers ---
                    elif current_note: # Only apply if note active
                        if char == "'": o_mod += 1; current_note.octave = o_mod
                        elif char == ",": o_mod -= 1; current_note.octave = o_mod
                        elif char == '_': u_count += 1
                        elif char == '-': h_count += 1
                        elif char == '.':
                            if not dot: dot = True
                            else: print(f"Warning: Multiple '.' L{line_idx+1} C{i+1}")
                        elif not char.isspace(): # Implicit end of note?
                            current_note = self._finalize_current_note(current_note, u_count, h_count, dot)
                            o_mod, u_count, h_count, dot = 0, 0, 0, False; self.is_inside_slur = False
                            i -= 1 # Re-process this char

                    # --- Spaces ---
                    elif char.isspace():
                        current_note = self._finalize_current_note(current_note, u_count, h_count, dot)
                        o_mod, u_count, h_count, dot = 0, 0, 0, False; self.is_inside_slur = False # Spaces also reset state/slur

                    # --- Unhandled ---
                    elif not self.is_inside_slur: # Don't warn if inside slur, might be text
                         pass # print(f"Warning: Skipping unexpected char '{char}' L{line_idx+1} C{i+1}") # Less noisy

                    i += 1 # Advance loop
                except Exception as e_inner: print(f"Error parsing L{line_idx+1} C{i+1}: {e_inner}"); i += 1 # Skip char on error

            # --- End of Line ---
            current_note = self._finalize_current_note(current_note, u_count, h_count, dot)
            o_mod, u_count, h_count, dot = 0, 0, 0, False
            self.is_inside_slur = False # Reset slur state at end of line

    def parse_multichar_token(self, line, index, start_char):
        token = start_char; consumed = 0; line_len = len(line)
        if start_char == '|':
            if index + 1 < line_len:
                if line[index+1] == ']': token = '|]'; consumed = 1
                elif line[index+1] == '|': token = "||"; consumed = 1
                elif line[index+1] == ':': token = "|:"; consumed = 1
                elif line[index+1] == '[':
                    alt_match = re.match(r"\|\|?\[(\d+)\.?.*", line[index:])
                    if alt_match:
                        end_alt = line.find(')', index)
                        token = line[index : end_alt+1] if end_alt != -1 else alt_match.group(0)
                        consumed = len(token) - 1
        elif start_char == ':':
             if index + 1 < line_len and line[index+1] == '|':
                  if index + 2 < line_len and line[index+2] == ':': token = ':|:'; consumed = 2
                  else: token = ':|'; consumed = 1
        elif start_char == '[':
             if index + 2 < line_len and line[index+1:index+3] == '|]': token = '[|]'; consumed = 2
        return token, consumed

    def parse_bars(self, token):
        """Generates Lilypond commands/bars, including structure braces."""
        token = token.strip()
        if token == "|": return "|"
        if token == "||": return "\\bar \"||\""
        if token == "[|]": return "\\bar \"[|]\""
        if token == "|:":
            self.alternative_closing_needed = 0 # Ensure clean state
            return "\\bar \"|:\""
        if token == ":|:": return "\\bar \":|:\""

        alt_match = re.match(r"\|\|?\[(\d+)\.?.*", token)
        if alt_match:
            if not self.alternative_opened:
                 volta_num = 2; prefix = f"\\repeat volta {volta_num} {{";
                 self.alternative_opened = True; self.alternative_closing_needed = 2
                 return prefix + " \\alternative { {" # Double {{ needed
            else: return "} {" # Start subsequent alternative

        if token == ":|":
            if self.alternative_opened: return "\\bar \":|.\" }" # Close first alt music block
            else: self.alternative_closing_needed = 0; return '\\bar ":|." '
        if token == '|]':
            if self.alternative_opened: return "\\bar \"|.\" }" # Close last alt music block
            else: self.alternative_closing_needed = 0; return '\\bar "|."'

        # print(f"Warning: Unknown bar token '{token}', using '|'") # Less noisy
        return '|'

    def parse_note_key(self, note_str):
        note_str = note_str.strip().lower()
        if not note_str: return "c"
        if len(note_str) == 1: return note_str if 'a' <= note_str <= 'g' else "c"
        elif len(note_str) == 2:
            if note_str.startswith('b') and 'a' <= note_str[1] <= 'g': return note_str[1] + "es"
            if note_str.startswith('#') and 'a' <= note_str[1] <= 'g': return note_str[1] + "is"
            if note_str.endswith('b') and 'a' <= note_str[0] <= 'g': return note_str[0] + "es"
            if note_str.endswith('#') and 'a' <= note_str[0] <= 'g': return note_str[0] + "is"
        # print(f"Warning: Could not parse key note '{note_str}', using C.") # Less noisy
        return "c"

    def to_lilypond(self):
        """Generates the Lilypond output string using absolute octaves and includes MIDI output block."""
        lines = []
        lines.append('\\version "2.18.2"')
        lines.append('\\language "english"')
        lines.append('')
        lines.append('\\header {')
        if self.song_title:
            escaped_title = self.song_title.replace('"', '\\"')
            lines.append(f'    title = "{escaped_title}"')
        lines.append('}')
        lines.append('')
        lines.append('\\score {')
        lines.append('  {') # Start music block (absolute octaves)
        lines.append('    \\clef treble')

        # --- Key Signature ---
        key_set = False
        if self.key:
            kv = self.key.split("=")
            mode = "\\major" if kv[0]=='1' else "\\minor"
            if len(kv) == 2:
                 key_note = self.parse_note_key(kv[1])
                 lines.append(f'    \\key {key_note} {mode}')
                 key_set = True
        if not key_set: lines.append('    \\key c \\major')

        if self.sig: lines.append(f'    \\time {self.sig}')
        if self.tempo: lines.append(f'    \\tempo 4 = {self.tempo}')
        lines.append('')

        # --- Format Notes and Music ---
        output_line = "    "
        item_count_on_line = 0; line_limit = 60

        for item in self.notes:
            item_str = ""
            is_structural_command = False

            if isinstance(item, Note):
                note_str = str(item)
                if item.slur_start: item_str += "("
                item_str += note_str
                if item.slur_end: item_str += ")"
                item_str += " "
            elif isinstance(item, str): # Barline or command
                 item_str_strip = item.strip()
                 if item_str_strip.startswith("\\") or item_str_strip.startswith("}"):
                     is_structural_command = True
                     if output_line.strip(): lines.append(output_line.strip())
                     indent = "  " if item_str_strip.startswith(("\\repeat", "\\alternative")) else "    "
                     if item_str_strip.endswith("}") and item_str_strip != "} {": indent = "    " # Closing braces more indented
                     lines.append(indent + item_str_strip)
                     output_line = "    "; item_count_on_line = 0
                     continue
                 else: item_str = item_str_strip + " " # Simple bar "|"

            output_line += item_str
            item_count_on_line += 1

            is_bar = isinstance(item, str) and "|" in item
            if is_bar and len(output_line) > line_limit:
                lines.append(output_line.strip())
                output_line = "    "
                item_count_on_line = 0

        if output_line.strip(): lines.append(output_line.strip())

        # Add closing braces for \alternative and \repeat if needed
        if self.alternative_closing_needed > 0:
            lines.append("  " + "}" * self.alternative_closing_needed)

        # --- Close Music Block and Add Layout/MIDI Blocks ---
        lines.append('  }') # Close the main music block { ... }
        lines.append('  \\layout {')
        lines.append('    \\context {')
        lines.append('      \\Score')
        lines.append('    }')
        lines.append('  }')
        lines.append('  \\midi {')  # Add MIDI block
        lines.append('    \\context {')
        lines.append('      \\Score')
        lines.append('    }')
        lines.append('  }')
        lines.append('}') # Close \score block
        return u"\n".join(lines)


    def parse_key_and_meters(self):
        key_pattern = re.compile(r"\{?\s*([16])\s*=\s*([A-Ga-g][#b]?)\s*,\s*([0-9]+/[0-9]+)\s*\}?", re.IGNORECASE)
        title_pattern = re.compile(r"\{?(.+)\}?")
        tempo_pattern = re.compile(r"\{?\s*J\s*=\s*([0-9]+)\s*\}?")

        p_title, p_key, p_tempo = False, False, False
        for t_line in self.title:
            parts = t_line.split("=", 1)
            if len(parts) != 2: continue
            key, value = parts[0].strip().lower(), parts[1].strip()

            if key == "keyandmeters" and not p_key:
                match = key_pattern.search(value)
                if match: self.key = f"{match.group(1)}={match.group(2).upper()}"; self.sig = match.group(3); p_key = True
                # else: print(f"Warn: Bad KeyAndMeters: {value}") # Less noisy
            elif key == "title" and not p_title:
                 match = title_pattern.match(value)
                 self.song_title = match.group(1).strip().strip('{}') if match else value.strip('{}')
                 p_title = True
            elif key == "expression" and not p_tempo:
                 match = tempo_pattern.search(value)
                 if match: self.tempo = match.group(1); p_tempo = True

# --- Conversion Function and Main ---
def convert(from_file, to_file):
    jpw = JpwFile()
    if not jpw.parse(from_file): print("Error: Parse failed."); return
    jpw.parse_key_and_meters()
    jpw.parse_voice_char_by_char()
    try:
        ly_output = jpw.to_lilypond()
        with io.open(to_file, "w", encoding='utf-8') as f_out: f_out.write(ly_output)
        print(f"Success: '{from_file}' -> '{to_file}'")
    except Exception as e: print(f"Error generating/writing Lilypond: {e}")

if __name__ == '__main__':
    parser = OptionParser(usage="usage: %prog -f <in.jpw> -t <out.ly>")
    parser.add_option("-f", "--from", dest="from_file", help="Input JPW file")
    parser.add_option("-t", "--to", dest="to_file", help="Output Lilypond .ly file")
    (opts, args) = parser.parse_args()
    if not opts.from_file or not opts.to_file: parser.error("Input and output files required (-f, -t)")
    convert(opts.from_file, opts.to_file)