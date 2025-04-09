# -*- coding: utf-8 -*-
import re
import xml.etree.ElementTree as ET
import xml.dom.minidom as minidom
from math import pow
import os
import datetime # For encoding date
import argparse # For command-line arguments

# --- Configuration & Mappings ---
KEY_SIGNATURE_FIFTHS = -1 # F Major / D minor (1 flat)
NOTE_MAP_F_MAJOR = {
    # Base octave assumption: 1-4 are octave 4, 5-7 are octave 5
    '1': ('F', 4), '2': ('G', 4), '3': ('A', 4), '4': ('B', 4), # B needs flat unless altered
    '5': ('C', 5), '6': ('D', 5), '7': ('E', 5)
}
DIVISIONS = 4 # Divisions per quarter note
BASE_DURATION_DIVISIONS = DIVISIONS # Quarter note = 4 divisions
DURATION_MAP = {
    1: '16th',
    2: 'eighth',
    3: 'eighth', # Dotted eighth base type is still eighth
    4: 'quarter',
    6: 'quarter', # Dotted quarter base type is still quarter
    8: 'half',
    12: 'half',    # Dotted half base type is still half
    16: 'whole'
    # Add more if needed
}

# --- Helper Functions ---

def pitch_to_musicxml(note_num, accidental_str, octave_str):
    """Converts Jianpu note info to MusicXML pitch elements."""
    if note_num not in NOTE_MAP_F_MAJOR:
        print(f"Warning: Unknown note number '{note_num}'")
        return None, None, None, None # Step, Alter, Octave, Accidental Type
    step, base_octave = NOTE_MAP_F_MAJOR[note_num]
    octave = base_octave + len(octave_str) # Each 'g' adds 1 octave
    alter = 0
    accidental_type = None # MusicXML accidental element ('sharp', 'flat', 'natural')
    is_b_note = (step == 'B')
    key_has_b_flat = (KEY_SIGNATURE_FIFTHS == -1) # True for F Major/D minor
    if accidental_str == '#':
        if is_b_note and key_has_b_flat: alter, accidental_type = 0, 'natural'
        else: alter, accidental_type = 1, 'sharp'
    elif accidental_str == 'b': alter, accidental_type = -1, 'flat'
    else: # No explicit accidental
        if is_b_note and key_has_b_flat: alter = -1
        else: alter = 0
    return step, alter, octave, accidental_type

def duration_to_musicxml(underscores, dots):
    """Calculates MusicXML duration, type, and dot info from underscores and dots."""
    base_duration = float(BASE_DURATION_DIVISIONS)
    # Ensure dots are strings before calling len()
    dots = dots if dots is not None else ""
    underscores = underscores if underscores is not None else ""

    num_underscores = len(underscores)
    num_dots = len(dots)
    current_duration = base_duration / pow(2, num_underscores)
    total_duration = current_duration
    dot_increment = current_duration
    for _ in range(num_dots):
        dot_increment /= 2.0
        total_duration += dot_increment
    total_duration = int(round(total_duration))
    type_duration_lookup = int(round(current_duration))
    note_type = DURATION_MAP.get(type_duration_lookup, 'quarter')
    has_dot = num_dots > 0
    return total_duration, note_type, has_dot, num_dots

def pretty_print_xml(element):
    """Returns a pretty-printed XML string with declaration."""
    rough_string = ET.tostring(element, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ", encoding="UTF-8").decode('utf-8')

def parse_jpwabc(jpwabc_content):
    """Parses the JPW-ABC content into a dictionary."""
    data = {'metadata': {}, 'options': {}, 'voice_measures': []} # Initialize voice_measures as list
    current_section = None
    voice_buffer = ""
    lines = jpwabc_content.splitlines()
    for line in lines:
        line = line.strip()
        if not line or line.startswith('//'): continue
        if line.startswith('.'):
            if current_section == 'voice' and voice_buffer:
                 measures_raw = [m.strip() for m in voice_buffer.split('|') if m.strip()]
                 if measures_raw: data['voice_measures'].extend(measures_raw) # Use extend to add multiple measures
                 voice_buffer = ""
            section_name = line[1:].lower().strip()
            current_section = section_name
            if current_section not in data and current_section != 'voice': data[current_section] = {}
            continue
        if current_section == 'options':
            if '=' in line: key, value = line.split('=', 1); data['options'][key.strip()] = value.strip()
        elif current_section == 'title':
             if '=' in line: key, value = line.split('=', 1); data['metadata'][key.strip().replace(' ', '').lower()] = value.strip()
        elif current_section == 'voice': voice_buffer += line
    if current_section == 'voice' and voice_buffer:
        measures_raw = [m.strip() for m in voice_buffer.split('|') if m.strip()]
        if measures_raw: data['voice_measures'].extend(measures_raw) # Use extend for final buffer processing
    return data


# --- create_musicxml function (CORRECTED REGEX and GROUP ACCESS) ---
def create_musicxml(parsed_data):
    # Level 1 Indentation
    if not parsed_data or not parsed_data.get('voice_measures'):
        print("Error: No voice data found to convert.")
        return None

    score_partwise = ET.Element("score-partwise", version="4.0")

    # --- Metadata ---
    work_title_text = parsed_data['metadata'].get('title', 'Untitled')
    work = ET.SubElement(score_partwise, "work")
    ET.SubElement(work, "work-title").text = work_title_text

    identification = ET.SubElement(score_partwise, "identification")
    encoding = ET.SubElement(identification, "encoding")
    ET.SubElement(encoding, "software").text = "JPW-ABC to MusicXML Converter (Python)"
    ET.SubElement(encoding, "encoding-date").text = datetime.date.today().isoformat()
    composer = parsed_data['metadata'].get('wordsbyandmusicby', '')
    if composer:
        parts = composer.split(':') if ':' in composer else composer.split('/')
        creator_type = "composer"; name = composer.strip()
        if len(parts) == 2:
            role, name = parts[0].strip(), parts[1].strip(); role_low = role.lower()
            if "music" in role_low: creator_type="composer"
            elif "lyrics" in role_low: creator_type="lyricist"
            elif "arranger" in role_low: creator_type="arranger"
        ET.SubElement(identification, "creator", type=creator_type).text = name

    # --- Part List ---
    part_list = ET.SubElement(score_partwise, "part-list")
    score_part = ET.SubElement(part_list, "score-part", id="P1")
    ET.SubElement(score_part, "part-name").text = work_title_text

    # --- Part Data ---
    part = ET.SubElement(score_partwise, "part", id="P1")

    measure_number = 0
    time_signature_str = "4/4"; key_sig_str = "F"
    key_meters_match = re.search(r'\{\s*1=([^,]+)\s*,\s*([^}]+)\s*\}', parsed_data['metadata'].get('keyandmeters', ''))
    if key_meters_match: key_sig_str = key_meters_match.group(1).strip(); time_signature_str = key_meters_match.group(2).strip()
    tempo_bpm = None; tempo_match = re.search(r'J=(\d+)', parsed_data['metadata'].get('expression', ''))
    if tempo_match: tempo_bpm = int(tempo_match.group(1))

    # CORRECTED Regular Expression: Handles note/rest + underscore + dot order, and tuplet structure
    note_pattern = re.compile(
        r"([#b]?)([1-7])(g*) (_*) (\.*)" +      # Note Grp 1-5 (Underscores G4, Dots G5)
        r"|(\{ \( (\d+) \} (.*?) \))" +          # Tuplet Grp 6(Marker G7 (\d+), Content G8) -> Note: G7 is digit only
        r"|(\$\( (.*?) \))" +                  # Directive Grp 9(Content G10)
        r"|(0) (_*) (\.*)",                    # Rest Grp 11(Underscores G12, Dots G13)
        re.VERBOSE                            # Use VERBOSE for clarity
    )


    # Level 1 Indentation for the loop
    for measure_str in parsed_data.get('voice_measures', []):
        # Level 2 Indentation
        measure_number += 1
        measure = ET.SubElement(part, "measure", number=str(measure_number))

        # Add attributes (key, time, clef) to the first measure
        if measure_number == 1:
            attributes = ET.SubElement(measure, "attributes")
            ET.SubElement(attributes, "divisions").text = str(DIVISIONS)
            key = ET.SubElement(attributes, "key")
            ET.SubElement(key, "fifths").text = str(KEY_SIGNATURE_FIFTHS)
            time = ET.SubElement(attributes, "time")
            if time_signature_str and '/' in time_signature_str:
                beats, beat_type = time_signature_str.split('/')
                ET.SubElement(time, "beats").text = beats; ET.SubElement(time, "beat-type").text = beat_type
            else:
                ET.SubElement(time, "beats").text = "4"; ET.SubElement(time, "beat-type").text = "4"
            clef = ET.SubElement(attributes, "clef")
            ET.SubElement(clef, "sign").text = "G"; ET.SubElement(clef, "line").text = "2"
            if tempo_bpm:
                direction = ET.SubElement(measure, "direction", placement="above")
                direction_type = ET.SubElement(direction, "direction-type")
                metronome = ET.SubElement(direction_type, "metronome", parentheses="no")
                ET.SubElement(metronome, "beat-unit").text = "quarter"
                ET.SubElement(metronome, "per-minute").text = str(tempo_bpm)
                sound = ET.SubElement(direction, "sound", tempo=str(tempo_bpm))

        # Process elements within the measure string
        pos = 0
        while pos < len(measure_str):
            # Level 3 Indentation
            match = note_pattern.match(measure_str, pos)
            if match:
                # Level 4 Indentation
                note_added = False
                # --- Matched a Note (Group 2 has number) ---
                if match.group(2):
                    accidental_str = match.group(1)
                    note_num = match.group(2)
                    octave_str = match.group(3)
                    underscores_str = match.group(4) # Group 4 is underscores
                    dots_str = match.group(5)        # Group 5 is dots
                    step, alter, octave, acc_type = pitch_to_musicxml(note_num, accidental_str, octave_str)
                    duration, note_type, has_dot, num_dots = duration_to_musicxml(underscores_str, dots_str)
                    if step:
                        note = ET.SubElement(measure, "note"); note_added = True
                        if acc_type: ET.SubElement(note, "accidental").text = acc_type
                        pitch = ET.SubElement(note, "pitch"); ET.SubElement(pitch, "step").text = step
                        if alter is not None and alter != 0: ET.SubElement(pitch, "alter").text = str(alter)
                        ET.SubElement(pitch, "octave").text = str(octave)
                        ET.SubElement(note, "duration").text = str(duration)
                        ET.SubElement(note, "type").text = note_type
                        for _ in range(num_dots): ET.SubElement(note, "dot")

                # --- Matched a Rest (Group 11 is '0') ---
                elif match.group(11):
                    rest_marker = match.group(11)
                    underscores_str = match.group(12) # Group 12 is underscores
                    dots_str = match.group(13)        # Group 13 is dots
                    duration, note_type, has_dot, num_dots = duration_to_musicxml(underscores_str, dots_str)
                    note = ET.SubElement(measure, "note"); note_added = True
                    ET.SubElement(note, "rest"); ET.SubElement(note, "duration").text = str(duration); ET.SubElement(note, "type").text = note_type
                    for _ in range(num_dots): ET.SubElement(note, "dot")

                # --- Matched a Tuplet (Group 6 is the whole match) ---
                elif match.group(6):
                    full_tuplet_str = match.group(6)
                    # Group 7 is the digit inside (\d+)
                    # Group 8 is the content (.*?)
                    ratio_digit_str = match.group(7)
                    tuplet_content = match.group(8)
                    print(f"Info: Parsing Tuplet: {full_tuplet_str}")

                    actual_notes = 3; normal_notes = 2 # Default triplet
                    if ratio_digit_str and ratio_digit_str.isdigit():
                        actual_notes = int(ratio_digit_str)
                    else:
                         print(f"Warning: Could not extract ratio digit from tuplet: {full_tuplet_str}")

                    inner_pos = 0
                    notes_in_tuplet_matches = []
                    while inner_pos < len(tuplet_content):
                         # Use the same pattern to find notes/rests within the tuplet content
                         inner_match = note_pattern.match(tuplet_content, inner_pos)
                         if inner_match: notes_in_tuplet_matches.append(inner_match); inner_pos = inner_match.end()
                         elif not tuplet_content[inner_pos].isspace(): inner_pos += 1 # Skip unknown non-space chars
                         else: inner_pos += 1 # Skip whitespace

                    for i, inner_match in enumerate(notes_in_tuplet_matches):
                        is_first = (i == 0); is_last = (i == len(notes_in_tuplet_matches) - 1)
                        tuplet_note = None
                        if inner_match.group(2): # Inner Note
                            # Indices 0-4 -> Groups 1-5 of the inner match
                            acc_inner, num_inner, oct_inner, under_inner, dot_inner = inner_match.groups()[0:5]
                            step, alter, octave, acc_type = pitch_to_musicxml(num_inner, acc_inner, oct_inner)
                            duration, note_type, has_dot, num_dots = duration_to_musicxml(under_inner, dot_inner)
                            if step:
                                tuplet_note = ET.SubElement(measure, "note")
                                if acc_type: ET.SubElement(tuplet_note, "accidental").text = acc_type
                                pitch = ET.SubElement(tuplet_note, "pitch"); ET.SubElement(pitch, "step").text = step
                                if alter is not None and alter != 0: ET.SubElement(pitch, "alter").text = str(alter)
                                ET.SubElement(pitch, "octave").text = str(octave)
                                ET.SubElement(tuplet_note, "duration").text = str(duration); ET.SubElement(tuplet_note, "type").text = note_type
                                for _ in range(num_dots): ET.SubElement(tuplet_note, "dot")
                        elif inner_match.group(11): # Inner Rest
                             # Indices 10-12 -> Groups 11-13 of the inner match
                             rest_marker_inner, under_inner, dot_inner = inner_match.groups()[10:13]
                             duration, note_type, has_dot, num_dots = duration_to_musicxml(under_inner, dot_inner)
                             tuplet_note = ET.SubElement(measure, "note"); ET.SubElement(tuplet_note, "rest")
                             ET.SubElement(tuplet_note, "duration").text = str(duration); ET.SubElement(tuplet_note, "type").text = note_type
                             for _ in range(num_dots): ET.SubElement(tuplet_note, "dot")
                        else: continue
                        # Add tuplet markings if a note/rest was created
                        if tuplet_note is not None:
                            note_added = True
                            tm = ET.SubElement(tuplet_note, "time-modification"); ET.SubElement(tm, "actual-notes").text = str(actual_notes); ET.SubElement(tm, "normal-notes").text = str(normal_notes)
                            notations = ET.SubElement(tuplet_note, "notations"); tuplet_type = "start" if is_first else ("stop" if is_last else "continue"); bracket_val = "yes" if is_first else "no"
                            ET.SubElement(notations, "tuplet", type=tuplet_type, number="1", bracket=bracket_val)

                # --- Matched a Directive (Group 9 is the whole match) ---
                elif match.group(9):
                     full_directive_str = match.group(9)
                     directive_content = match.group(10) # Content is Group 10
                     print(f"Info: Found directive: $({directive_content}) - adding as text direction.")
                     direction = ET.SubElement(measure, "direction", placement="above"); direction_type = ET.SubElement(direction, "direction-type"); ET.SubElement(direction_type, "words").text = f"$({directive_content})"

                # --- Advance Position ---
                pos = match.end()

            else:
                # No match, potentially whitespace or unrecognized char, skip it
                if pos < len(measure_str) and not measure_str[pos].isspace():
                     # print(f"Warning: Skipping unrecognized character '{measure_str[pos]}' in measure {measure_number} at pos {pos}")
                     pass # Silently skip for now
                pos += 1

    # Level 1 Indentation
    return score_partwise


# --- Execution ---
if __name__ == "__main__": # Standard practice for executable scripts
    parser = argparse.ArgumentParser(description='Convert JPW-ABC file to MusicXML.')
    parser.add_argument('-f', '--file', required=True, help='Input JPW-ABC file path.')
    parser.add_argument('-t', '--target', required=True, help='Output MusicXML file path.')
    args = parser.parse_args()

    input_filepath = args.file
    output_filepath = args.target
    jpwabc_input_content = None

    # --- UPDATED File Reading with Encoding Fallback ---
    try:
        # Try reading with utf-16 first (handles BOM FF FE or FE FF)
        with open(input_filepath, 'r', encoding='utf-16') as f_in:
             jpwabc_input_content = f_in.read()
        print(f"Read input from: {input_filepath} (using utf-16)")
    except FileNotFoundError:
        print(f"Error: Input file not found: {input_filepath}")
        exit(1)
    except UnicodeDecodeError:
        # Fallback if utf-16 failed (maybe it's utf-8 with BOM or other)
        print(f"Warning: Failed to read {input_filepath} as utf-16. Trying utf-8-sig...")
        try:
            # Try utf-8-sig (handles utf-8 with BOM EF BB BF)
            with open(input_filepath, 'r', encoding='utf-8-sig') as f_in:
                jpwabc_input_content = f_in.read()
            print(f"Read input from: {input_filepath} (using utf-8-sig)")
        except Exception as e_fallback:
            # If all known encodings fail, report error
            print(f"Error reading input file {input_filepath} with fallback encodings. Please check file encoding. Error: {e_fallback}")
            exit(1)
    except Exception as e:
        # Catch other potential errors during file reading
        print(f"Error reading input file {input_filepath}: {e}")
        exit(1)
    # --- End UPDATED File Reading ---

    if jpwabc_input_content is None:
        print("Error: Failed to read input file content.")
        exit(1)

    # 1. Parse the JPW-ABC data
    parsed_jpw_data = parse_jpwabc(jpwabc_input_content)

    # 2. Create the MusicXML structure
    musicxml_element = create_musicxml(parsed_jpw_data)

    # 3. Generate the XML string and save to file
    if musicxml_element is not None:
        xml_output_string = pretty_print_xml(musicxml_element)

        try:
            # Always write output as standard UTF-8
            with open(output_filepath, "w", encoding="utf-8") as f_out:
                f_out.write(xml_output_string)
            print(f"\nSuccessfully saved MusicXML to: {output_filepath}")

        except IOError as e:
            print(f"\nError: Could not write file '{output_filepath}'. Reason: {e}")
        except Exception as e:
            print(f"\nAn unexpected error occurred during file writing: {e}")

    else:
        print("Failed to generate MusicXML structure.")