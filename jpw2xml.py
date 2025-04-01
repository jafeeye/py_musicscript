#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from optparse import OptionParser
import re
import io
import sys
import math
import xml.etree.ElementTree as ET
from xml.dom import minidom # For pretty printing XML

# --- MusicXML Constants and Helpers ---
# MusicXML <divisions>: Ticks per quarter note. Higher value allows for finer duration representation.
# Common values: 24, 48, 96, 480. Let's use 24 for simplicity.
DIVISIONS_PER_QUARTER = 24

# --- JPW 解析輔助函數 (從之前的腳本修改) ---
def calculate_beats_from_jpw(underscore_count, hyphen_count, has_dot):
    """Calculates beats based on JPW rules."""
    current_beats = 1.0 * (0.5 ** underscore_count) + float(hyphen_count)
    if has_dot: current_beats *= 1.5
    return current_beats

# MIDI Note number to Pitch Name mapping (for reference, might need adjustment based on key)
MIDI_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']

def get_diatonic_pitch(jpw_num_str, key_root_midi, key_mode):
    """ Calculates the diatonic MIDI pitch number for a JPW number in a given key."""
    # Major scale intervals from root (0=root, 1=Maj2nd, etc.)
    major_intervals = [0, 2, 4, 5, 7, 9, 11]
    # Natural Minor scale intervals from root
    minor_intervals = [0, 2, 3, 5, 7, 8, 10]

    scale_intervals = major_intervals if key_mode == 0 else minor_intervals

    try:
        jpw_idx = int(jpw_num_str) - 1 # JPW 1 is index 0
        if 0 <= jpw_idx < 7:
            interval = scale_intervals[jpw_idx]
            # Calculate diatonic pitch relative to C0, then add key root offset
            base_midi_note = key_root_midi + interval
            return base_midi_note
        else:
            return None # Invalid JPW number
    except ValueError:
        return None

def get_key_info(key_str):
    """ Parses JPW key string like '1=C' or '6=Am' into root MIDI note and mode."""
    # Default to C Major
    key_root_midi = 60 # Middle C (C4) as reference root for mode 1
    key_mode = 0 # 0=major, 1=minor

    match = re.match(r"([16])=([A-Ga-g])([#b])?", key_str)
    if match:
        mode_num, root_note_name, accidental = match.groups()
        key_mode = 0 if mode_num == '1' else 1

        # Map root note name to MIDI base relative to C (C=0, D=2, etc.)
        note_map = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}
        base_offset = note_map.get(root_note_name.upper(), 0)

        # Calculate root MIDI note (assuming octave 4 for sharps/flats naming)
        key_root_midi = 60 + base_offset # Start with natural note MIDI number in octave 4
        if accidental == '#': key_root_midi += 1
        elif accidental == 'b': key_root_midi -= 1

        # If minor mode (6=...), the root specified is the *relative minor*'s root.
        # A minor's root is MIDI 69 (A4). C major's root is MIDI 60 (C4).
        # For simplicity in diatonic calculation, we might still use the relative major's root,
        # but the `<key>` element in MusicXML uses the specified root.
        # Let's return the specified root and the mode.

    # MusicXML <fifths> calculation based on MIDI root
    # C=0, G=1, D=2... F=-1, Bb=-2...
    fifths_map = {
        0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, # Sharps (relative to C)
        5: -1, 10: -2, 3: -3, 8: -4, 1: -5 # Flats (relative to C)
    }
    # Normalize root MIDI to 0-11 range to find fifths
    normalized_root = key_root_midi % 12
    key_fifths = fifths_map.get(normalized_root, 0) # Default to 0 (C) if weird root

    # Adjust fifths for minor keys relative to their parallel major if needed,
    # but MusicXML standard uses fifths of the specified key signature.
    # E.g., A minor has the same signature as C major (0 fifths).
    # G minor has the same signature as Bb major (-2 fifths).
    if key_mode == 1: # Minor key
        # Relative major is 3 semitones up
        relative_major_root = (key_root_midi + 3) % 12
        key_fifths = fifths_map.get(relative_major_root, 0)

    return key_root_midi, key_mode, key_fifths


def jpw_pitch_to_musicxml(jpw_num_str, jpw_oct_mod, jpw_prefix, key_root_midi, key_mode):
    """ Converts JPW pitch info to MusicXML pitch components (step, alter, octave)."""
    if jpw_num_str == '0': return None # Rest

    # 1. Calculate base diatonic MIDI note based on key
    diatonic_midi = get_diatonic_pitch(jpw_num_str, key_root_midi, key_mode)
    if diatonic_midi is None: return None # Invalid JPW number

    # 2. Apply explicit JPW accidental (# or b)
    actual_midi = diatonic_midi
    explicit_alter = 0
    if jpw_prefix == '#': actual_midi += 1; explicit_alter = 1
    elif jpw_prefix == 'b': actual_midi -= 1; explicit_alter = -1

    # 3. Apply JPW octave modifier (, or ') relative to the key's assumed base octave
    # Let's assume the key_root_midi calculated was in octave 4 (MIDI 60-71 range)
    # and this corresponds to JPW's base octave (mod 0).
    base_octave = key_root_midi // 12 # Octave number of the key root (C4=5, G4=5, A4=5...)
    # Correct approach: Calculate base octave based on the *diatonic* note in the key
    base_diatonic_octave = diatonic_midi // 12
    # The final octave is the diatonic note's octave + the JPW modifier
    final_midi_octave = base_diatonic_octave + jpw_oct_mod
    # Recalculate the final MIDI note number with the final octave
    note_in_octave = actual_midi % 12
    final_midi_note = final_midi_octave * 12 + note_in_octave

    # 4. Convert final MIDI note to MusicXML step, alter, octave
    musicxml_octave = str(final_midi_note // 12) # MusicXML octave convention
    note_index = final_midi_note % 12
    musicxml_step = MIDI_NOTE_NAMES[note_index][0] # C, D, E...

    # Determine alteration based on *final* MIDI vs natural note
    natural_midi = final_midi_octave * 12 + {'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[musicxml_step]
    musicxml_alter = str(final_midi_note - natural_midi) # 1 for sharp, -1 for flat, 0 for natural

    return musicxml_step, musicxml_alter, musicxml_octave


def beats_to_musicxml_duration(beats):
    """ Converts beats (float, quarter=1.0) to MusicXML duration elements. """
    # Calculate MusicXML <duration> (integer ticks)
    xml_duration = int(round(beats * DIVISIONS_PER_QUARTER))

    # Determine MusicXML <type> (note shape) and <dot/>
    # This requires mapping beats back to standard types
    tolerance = 0.01
    note_types = {
        4.0: "whole", 3.0: "half", 2.0: "half", 1.5: "quarter", 1.0: "quarter",
        0.75: "eighth", 0.5: "eighth", 0.375: "16th", 0.25: "16th",
        0.1875: "32nd", 0.125: "32nd"
    }
    dots = 0
    xml_type = "quarter" # Default

    # Find closest standard duration type
    best_match_type = "quarter"
    min_diff = abs(beats - 1.0)

    type_beats_map = { "whole": 4.0, "half": 2.0, "quarter": 1.0, "eighth": 0.5,
                       "16th": 0.25, "32nd": 0.125, "64th": 0.0625 } # Add more if needed

    for name, base_beats in type_beats_map.items():
        # Check non-dotted
        diff = abs(beats - base_beats)
        if diff < min_diff: min_diff = diff; best_match_type = name; dots = 0
        # Check dotted
        diff_dot = abs(beats - base_beats * 1.5)
        if diff_dot < min_diff: min_diff = diff_dot; best_match_type = name; dots = 1
        # Check double-dotted (less common)
        diff_dot2 = abs(beats - base_beats * 1.75)
        if diff_dot2 < min_diff: min_diff = diff_dot2; best_match_type = name; dots = 2

    xml_type = best_match_type
    dot_elements = [ET.Element("dot") for _ in range(dots)]

    return xml_duration, xml_type, dot_elements

# --- JpwToMusicXml Class ---
class JpwToMusicXml:
    def __init__(self):
        self.title = "轉換自 JPW"
        self.jpw_key_str = "1=C"
        self.jpw_time_sig = "4/4"
        self.jpw_tempo_str = ""
        self.voice_events = [] # Stores parsed events: {'type': 'note'/'rest'/'bar'/'attributes', ...}

    def parse_jpw(self, jpw_file_path):
        """Reads and parses the JPW file into voice_events."""
        # ( Reuse file reading logic from JpwToDocx, trying encodings )
        encodings_to_try = ['utf-16', 'gbk', 'utf-8-sig', 'utf-8']
        jpw_content = None
        for enc in encodings_to_try:
            try:
                with io.open(jpw_file_path, 'r', encoding=enc) as f: jpw_content = f.read()
                print(f"Read '{jpw_file_path}' with {enc}.")
                break
            except Exception: continue
        if jpw_content is None: print(f"Error: Cannot read/decode '{jpw_file_path}'."); return False

        # Parse sections
        current_section = None; voice_lines_raw = []; title_lines_raw = []
        for line in jpw_content.splitlines():
            line_strip = line.strip()
            if not line_strip or line_strip.startswith('//'): continue
            if line.startswith("."): current_section = line[1:].strip().lower(); continue
            if current_section == 'title': title_lines_raw.append(line)
            elif current_section == 'voice': voice_lines_raw.append(line)

        # Parse Metadata from Title section
        self.parse_jpw_title_section(title_lines_raw)
        # Parse Voice section into events
        self.parse_jpw_voice_section(voice_lines_raw)

        return True

    def parse_jpw_title_section(self, title_lines):
        """Extracts metadata from JPW .Title lines."""
        key_pattern = re.compile(r"\{?\s*([16])\s*=\s*([A-Ga-g][#b]?)\s*,\s*([0-9]+/[0-9]+)\s*\}?", re.IGNORECASE)
        title_pattern = re.compile(r"\{?(.+)\}?")
        tempo_pattern = re.compile(r"\{?\s*J\s*=\s*([0-9]+)\s*\}?")

        for line in title_lines:
            parts = line.split("=", 1)
            if len(parts) != 2: continue
            key = parts[0].strip().lower(); value = parts[1].strip()

            if key == "keyandmeters":
                match = key_pattern.search(value)
                if match: self.jpw_key_str = f"{match.group(1)}={match.group(2).upper()}"; self.jpw_time_sig = match.group(3)
            elif key == "title":
                 match = title_pattern.match(value)
                 self.title = match.group(1).strip().strip('{}') if match else value.strip('{}')
            elif key == "expression":
                 match = tempo_pattern.search(value)
                 if match: self.jpw_tempo_str = f"J={match.group(1)}"
        print(f"Parsed JPW Metadata: Title='{self.title}', Key='{self.jpw_key_str}', Time='{self.jpw_time_sig}', Tempo='{self.jpw_tempo_str}'")

    def parse_jpw_voice_section(self, voice_lines):
        """Parses JPW .Voice lines into a list of musical events."""
        self.voice_events = []
        current_note_attrs = {'jpw_num': None, 'oct_mod': 0, 'prefix': '', 'u_count': 0, 'h_count': 0, 'dot': False, 'slur_start': False, 'slur_end': False}
        is_inside_slur = False

        def finalize_and_add_event(attrs):
            if attrs['jpw_num'] is not None:
                beats = calculate_beats_from_jpw(attrs['u_count'], attrs['h_count'], attrs['dot'])
                event = {'type': 'rest' if attrs['jpw_num'] == '0' else 'note'}
                event['beats'] = beats
                if event['type'] == 'note':
                    event['jpw_num'] = attrs['jpw_num']
                    event['oct_mod'] = attrs['oct_mod']
                    event['prefix'] = attrs['prefix']
                    event['slur_start'] = attrs['slur_start']
                    event['slur_end'] = attrs['slur_end']
                self.voice_events.append(event)
                # Reset for next note
                attrs.update({'jpw_num': None, 'oct_mod': 0, 'prefix': '', 'u_count': 0, 'h_count': 0, 'dot': False, 'slur_start': False, 'slur_end': False})

        for line_idx, line in enumerate(voice_lines):
            i, line_len = 0, len(line)
            while i < line_len:
                char = line[i]
                # Skip comments and formatting commands first
                if line[i:].startswith("//"): break # End of line comment
                if line[i:].startswith("$("): # Skip JPW formatting command
                    end_cmd = line.find(')', i)
                    i = end_cmd + 1 if end_cmd != -1 else line_len
                    continue
                if char.isspace(): i += 1; continue # Skip whitespace

                # Handle musical notation
                if char.isdigit():
                    finalize_and_add_event(current_note_attrs) # Finalize previous if any
                    current_note_attrs['jpw_num'] = char
                    if is_inside_slur: current_note_attrs['slur_start'] = True; is_inside_slur = False # Apply slur start
                elif current_note_attrs['jpw_num'] is not None: # Modifiers only apply if note active
                    if char == "'": current_note_attrs['oct_mod'] += 1
                    elif char == ",": current_note_attrs['oct_mod'] -= 1
                    elif char == '_': current_note_attrs['u_count'] += 1
                    elif char == '-': current_note_attrs['h_count'] += 1
                    elif char == '.': current_note_attrs['dot'] = True
                    elif char == '#': current_note_attrs['prefix'] = '#'
                    elif char == 'b': current_note_attrs['prefix'] = 'b'
                    elif char == '(': # Start slur mark BEFORE next note
                        finalize_and_add_event(current_note_attrs)
                        is_inside_slur = True
                    elif char == ')': # End slur mark AFTER this note
                        current_note_attrs['slur_end'] = True
                        finalize_and_add_event(current_note_attrs) # Finalize note with slur end
                    elif char == '{': # Skip decorations for now
                        end_dec = line.find('}', i)
                        i = end_dec if end_dec != -1 else i # Skip to end or stay if no '}'
                    elif char in '|:[]': # Barlines finalize note
                        finalize_and_add_event(current_note_attrs)
                        bar_token, consumed = self.parse_jpw_multichar_bar(line, i, char); i += consumed
                        self.voice_events.append({'type': 'barline', 'style': bar_token}) # Add barline event
                    else: # Unknown char after note, finalize note
                        finalize_and_add_event(current_note_attrs)
                        i -= 1 # Re-process unknown char if needed
                elif char == '(': is_inside_slur = True # Slur starts before any note
                elif char == ')': # Slur ends - apply to previous note if possible
                    if self.voice_events and self.voice_events[-1]['type'] == 'note':
                         self.voice_events[-1]['slur_end'] = True
                    is_inside_slur = False # Assume slur ends
                elif char in '|:[]': # Barline without preceding note
                    bar_token, consumed = self.parse_jpw_multichar_bar(line, i, char); i += consumed
                    self.voice_events.append({'type': 'barline', 'style': bar_token})
                elif char == '{': # Skip decorations
                    end_dec = line.find('}', i); i = end_dec if end_dec != -1 else i
                # else: print(f"Skipping char '{char}'")

                i += 1
            # End of line
            finalize_and_add_event(current_note_attrs)
            is_inside_slur = False # Reset slur state at line end

    def parse_jpw_multichar_bar(self, line, index, start_char):
        """ Parses JPW multi-char barlines."""
        # Reuse logic from previous script (midi_to_jpw or similar) if available
        # For now, simple version:
        token = start_char; consumed = 0; line_len = len(line)
        if start_char == '|':
            if index + 1 < line_len:
                if line[index+1] == ']': token = '|]'; consumed = 1
                elif line[index+1] == '|': token = "||"; consumed = 1
                elif line[index+1] == ':': token = "|:"; consumed = 1
                elif line[index+1] == '[': # Start alternative
                     alt_match = re.match(r"\|\|?\[(\d+)\.?.*", line[index:])
                     if alt_match: token = alt_match.group(0); consumed = len(token) - 1
        elif start_char == ':':
             if index + 1 < line_len and line[index+1] == '|':
                  if index + 2 < line_len and line[index+2] == ':': token = ':|:'; consumed = 2
                  else: token = ':|'; consumed = 1
        elif start_char == '[':
             if index + 2 < line_len and line[index+1:index+3] == '|]': token = '[|]'; consumed = 2
        return token, consumed

    def build_musicxml(self):
        """Builds the MusicXML ElementTree from parsed voice_events."""
        root = ET.Element("score-partwise", version="3.1") # Use a common version

        # Part List
        part_list = ET.SubElement(root, "part-list")
        score_part = ET.SubElement(part_list, "score-part", id="P1")
        ET.SubElement(score_part, "part-name").text = self.title if self.title else "Music"

        # Part
        part = ET.SubElement(root, "part", id="P1")

        measure_number = 0
        current_measure = None
        first_measure = True
        key_root_midi, key_mode, key_fifths = get_key_info(self.jpw_key_str)
        time_num, time_den = self.jpw_time_sig.split('/')

        # Track ongoing slurs/ties (MusicXML ID based)
        slur_counter = 0
        active_slurs = {} # { slur_number: start_note_element }

        for event in self.voice_events:
            # Start new measure if needed
            if current_measure is None:
                measure_number += 1
                current_measure = ET.SubElement(part, "measure", number=str(measure_number))

                # Add attributes to the first measure or when they change (not implemented yet)
                if first_measure:
                    attributes = ET.SubElement(current_measure, "attributes")
                    ET.SubElement(attributes, "divisions").text = str(DIVISIONS_PER_QUARTER)
                    key = ET.SubElement(attributes, "key")
                    ET.SubElement(key, "fifths").text = str(key_fifths)
                    # Mode element is optional but good practice
                    ET.SubElement(key, "mode").text = "minor" if key_mode == 1 else "major"
                    time = ET.SubElement(attributes, "time")
                    ET.SubElement(time, "beats").text = time_num
                    ET.SubElement(time, "beat-type").text = time_den
                    clef = ET.SubElement(attributes, "clef")
                    ET.SubElement(clef, "sign").text = "G" # Assume Treble
                    ET.SubElement(clef, "line").text = "2"
                    first_measure = False
                    # Add Tempo
                    if self.jpw_tempo_str.startswith("J="):
                         bpm = int(self.jpw_tempo_str.split('=')[1])
                         direction = ET.SubElement(current_measure, "direction", placement="above")
                         direction_type = ET.SubElement(direction, "direction-type")
                         metronome = ET.SubElement(direction_type, "metronome", parentheses="no")
                         ET.SubElement(metronome, "beat-unit").text = "quarter"
                         ET.SubElement(metronome, "per-minute").text = str(bpm)
                         ET.SubElement(direction, "sound", tempo=str(bpm)) # Sound tempo needed for playback


            # Process event type
            if event['type'] == 'note':
                note_el = ET.SubElement(current_measure, "note")
                pitch_info = jpw_pitch_to_musicxml(event['jpw_num'], event['oct_mod'], event['prefix'], key_root_midi, key_mode)
                if pitch_info:
                    pitch_el = ET.SubElement(note_el, "pitch")
                    ET.SubElement(pitch_el, "step").text = pitch_info[0]
                    if pitch_info[1] != '0': ET.SubElement(pitch_el, "alter").text = pitch_info[1]
                    ET.SubElement(pitch_el, "octave").text = pitch_info[2]
                    # Check for explicit accidental needed (compare to key sig) - Simplified: always add if explicit '#' or 'b'
                    if event['prefix']:
                        acc_map = {'#':'sharp', 'b':'flat'}
                        ET.SubElement(note_el, "accidental").text = acc_map.get(event['prefix'], "")

                xml_duration, xml_type, dot_elements = beats_to_musicxml_duration(event['beats'])
                ET.SubElement(note_el, "duration").text = str(xml_duration)
                ET.SubElement(note_el, "type").text = xml_type
                for dot_el in dot_elements: note_el.append(dot_el)
                ET.SubElement(note_el, "voice").text = "1" # Default voice

                # Handle slurs
                notations = None
                if event.get('slur_start', False):
                    slur_counter += 1
                    if notations is None: notations = ET.SubElement(note_el, "notations")
                    ET.SubElement(notations, "slur", type="start", number=str(slur_counter), placement="above")
                    active_slurs[slur_counter] = note_el # Store reference if needed, simple version doesn't use it
                if event.get('slur_end', False):
                     if notations is None: notations = ET.SubElement(note_el, "notations")
                     # Find the most recent slur number to close (simplistic: assume last opened)
                     if slur_counter in active_slurs:
                         ET.SubElement(notations, "slur", type="stop", number=str(slur_counter))
                         del active_slurs[slur_counter] # Remove closed slur
                         # Decrement? Only if strict nesting is guaranteed. Safter not to for simple case.


            elif event['type'] == 'rest':
                note_el = ET.SubElement(current_measure, "note")
                ET.SubElement(note_el, "rest")
                xml_duration, xml_type, dot_elements = beats_to_musicxml_duration(event['beats'])
                ET.SubElement(note_el, "duration").text = str(xml_duration)
                ET.SubElement(note_el, "type").text = xml_type
                for dot_el in dot_elements: note_el.append(dot_el)
                ET.SubElement(note_el, "voice").text = "1"

            elif event['type'] == 'barline':
                barline_el = ET.SubElement(current_measure, "barline", location="right")
                style = event['style']
                bar_style = "light-light" if style == "||" else \
                            "light-heavy" if style == "|]" else \
                            "heavy-light" if style == ":|:" else \
                            "regular" # Default for | and unknown
                ET.SubElement(barline_el, "bar-style").text = bar_style

                # Handle repeats (basic)
                if style == "|:":
                    repeat_el = ET.SubElement(barline_el, "repeat", direction="forward")
                elif style == ":|":
                    repeat_el = ET.SubElement(barline_el, "repeat", direction="backward")

                # End the current measure after adding the barline
                current_measure = None


        # Final cleanup: Ensure last measure exists if loop ended mid-measure
        if current_measure is None and measure_number == 0 : # Handle empty input case
             measure_number += 1
             current_measure = ET.SubElement(part, "measure", number=str(measure_number))
             # Add default attributes if file was completely empty except header
             attributes = ET.SubElement(current_measure, "attributes")
             ET.SubElement(attributes, "divisions").text = str(DIVISIONS_PER_QUARTER)
             # Add default key, time, clef


        # Add final barline if the last event wasn't a barline ending the measure
        if current_measure is not None:
             last_barline = current_measure.find("barline")
             if last_barline is None:
                 barline_el = ET.SubElement(current_measure, "barline", location="right")
                 ET.SubElement(barline_el, "bar-style").text = "light-heavy" # Standard end bar


        return ET.ElementTree(root)

    def write_musicxml(self, output_xml_path):
        """Builds and writes the MusicXML file."""
        try:
            tree = self.build_musicxml()
            # Pretty print the XML
            xml_string = ET.tostring(tree.getroot(), encoding='unicode')
            dom = minidom.parseString(xml_string)
            pretty_xml_as_string = dom.toprettyxml(indent="  ", encoding="UTF-8")

            # Write the pretty-printed XML with declaration
            with open(output_xml_path, "wb") as f: # Write bytes
                 # Add XML declaration manually as toprettyxml doesn't include full version/encoding
                 f.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
                 # Remove the declaration generated by toprettyxml if present
                 pretty_xml_lines = pretty_xml_as_string.splitlines()
                 if pretty_xml_lines[0].startswith(b'<?xml'):
                      f.write(b"\n".join(pretty_xml_lines[1:]))
                 else:
                      f.write(pretty_xml_as_string)

            print(f"Successfully created MusicXML: '{output_xml_path}'")
        except Exception as e:
            print(f"Error building or writing MusicXML: {e}")
            import traceback; traceback.print_exc()


# --- Main Execution ---
def convert_jpw_to_musicxml(from_file, to_file):
    converter = JpwToMusicXml()
    if not converter.parse_jpw(from_file):
        print("Error: JPW parsing failed.")
        return
    converter.write_musicxml(to_file)


if __name__ == '__main__':
    parser = OptionParser(usage="usage: %prog -f <input.jpw> -t <output.musicxml>")
    parser.add_option("-f", "--from", dest="from_file", help="Input JPW file")
    parser.add_option("-t", "--to", dest="to_file", help="Output MusicXML file (.musicxml or .xml)")
    (opts, args) = parser.parse_args()
    if not opts.from_file or not opts.to_file:
        parser.error("Input and output files required (-f, -t)")
    convert_jpw_to_musicxml(opts.from_file, opts.to_file)