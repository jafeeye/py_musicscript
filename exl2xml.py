import xml.etree.ElementTree as ET
import sys
import argparse
import os

# --- Reusable helper functions (create_defaults_element, find_defaults_insert_index, safe_remove_child) ---
# (Keep these functions exactly as they were)
def create_defaults_element():
    """ Creates standard <defaults> element. """
    defaults = ET.Element('defaults')
    scaling = ET.SubElement(defaults, 'scaling')
    ET.SubElement(scaling, 'millimeters').text = '6.99911'; ET.SubElement(scaling, 'tenths').text = '40'
    page_layout = ET.SubElement(defaults, 'page-layout')
    ET.SubElement(page_layout, 'page-height').text = '1696.94'; ET.SubElement(page_layout, 'page-width').text = '1200.48'
    margins_even = ET.SubElement(page_layout, 'page-margins', {'type': 'even'})
    ET.SubElement(margins_even, 'left-margin').text = '85.7252'; ET.SubElement(margins_even, 'right-margin').text = '85.7252'
    ET.SubElement(margins_even, 'top-margin').text = '85.7252'; ET.SubElement(margins_even, 'bottom-margin').text = '85.7252'
    margins_odd = ET.SubElement(page_layout, 'page-margins', {'type': 'odd'})
    ET.SubElement(margins_odd, 'left-margin').text = '85.7252'; ET.SubElement(margins_odd, 'right-margin').text = '85.7252'
    ET.SubElement(margins_odd, 'top-margin').text = '85.7252'; ET.SubElement(margins_odd, 'bottom-margin').text = '85.7252'
    appearance = ET.SubElement(defaults, 'appearance')
    ET.SubElement(appearance, 'line-width', {'type': 'staff'}).text = '1.1'; ET.SubElement(appearance, 'line-width', {'type': 'light barline'}).text = '1.8'
    ET.SubElement(appearance, 'line-width', {'type': 'heavy barline'}).text = '5.5'; ET.SubElement(appearance, 'line-width', {'type': 'stem'}).text = '1'
    ET.SubElement(appearance, 'line-width', {'type': 'beam'}).text = '5'; ET.SubElement(appearance, 'note-size', {'type': 'grace'}).text = '70'
    ET.SubElement(defaults, 'music-font', {'font-family': 'Maestro', 'font-size': '20.4'})
    ET.SubElement(defaults, 'word-font', {'font-family': 'Times New Roman', 'font-size': '10'})
    ET.SubElement(defaults, 'lyric-font', {'font-family': 'Times New Roman', 'font-size': '10'})
    return defaults

def find_defaults_insert_index(root):
    """ Finds index after <identification> for inserting <defaults>. """
    identification_idx = -1
    for i, child in enumerate(list(root)):
        if child.tag == 'identification': identification_idx = i; break
    return identification_idx + 1 if identification_idx != -1 else (1 if len(list(root)) > 0 else 0)

def safe_remove_child(parent, child):
    """ Removes child from parent only if it's a direct child. """
    if parent is None or child is None: return False
    try: list(parent).index(child); parent.remove(child); return True
    except (ValueError, Exception): return False
# --- End Helper Functions ---

# --- Main Processing Function ---

def fix_transpose_key_rebuild_measure1(input_file, output_file):
    """
    Parses MusicXML, applies general fixes, TRANSPOSES KEY SIGNATURE UP one step,
    reconstructs Measure 1 notes using READ original musical data and reference structure.
    Preserves text elsewhere. NOTE: Only key signature changes, not pitches.
    """
    try:
        parser = ET.XMLParser(encoding="utf-8")
        tree = ET.parse(input_file, parser=parser)
        root = tree.getroot()

        print(f"Processing '{input_file}' for Finale (Transposing Key Sig, Rebuilding M1)...")

        # --- 1. Perform General Fixes ---
        print("  Applying general fixes...")
        # (General fixes code remains the same)
        attributes_removed_count = 0
        metadata_elements_to_clean = [('movement-title', '.'), ('creator', './/identification/creator'), ('rights', './/identification/rights')]
        for tag_name, path in metadata_elements_to_clean:
            for element in root.findall(path):
                if element.tag == tag_name:
                    if element.attrib.pop('relative-x', None): attributes_removed_count += 1
                    if element.attrib.pop('relative-y', None): attributes_removed_count += 1
        #if attributes_removed_count > 0: print(f"    Removed {attributes_removed_count} relative-x/y from metadata.") # Less verbose

        identification_element = root.find('identification')
        if identification_element is not None:
            desc = identification_element.find('description');
            if desc is not None and safe_remove_child(identification_element, desc): pass # print("    Removed misplaced <description>.")
            encoding_element = identification_element.find('encoding')
            if encoding_element is not None:
                enc_date = encoding_element.find('encoding-date')
                if enc_date is not None and (not enc_date.text or not enc_date.text.strip()):
                    if safe_remove_child(encoding_element, enc_date): pass # print("    Removed empty <encoding-date>.")
        # else: print("    Warning: <identification> section not found.")

        subtitle = root.find('movement-subtitle');
        if subtitle is not None and safe_remove_child(root, subtitle): pass # print("    Removed misplaced <movement-subtitle>.")

        root.set('version', '4.0'); # print("    Set score-partwise version to 4.0.")

        if root.find('defaults') is None:
            defaults_element = create_defaults_element(); insert_idx = find_defaults_insert_index(root)
            root.insert(insert_idx, defaults_element); print(f"    Injected <defaults> section.")
        # else: print("    <defaults> section already exists.")
        print("  General fixes applied.")


        # --- 2. Rebuild Measure 1 ---
        print("  Rebuilding Measure 1...")
        part1 = root.find('.//part[@id="P1"]')
        if part1 is None: raise ValueError("Could not find <part id='P1'>")
        measure1 = part1.find('./measure[@number="1"]')
        if measure1 is None: raise ValueError("Could not find <measure number='1'> in Part P1")

        # --- Store original Measure 1 data ---
        original_attributes_elem = measure1.find('attributes')
        original_notes_elems = list(measure1.findall('note'))
        original_left_barline = measure1.find('barline[@location="left"]')
        original_right_barline = measure1.find('barline[@location="right"]')

        if original_attributes_elem is None: raise ValueError("Measure 1 is missing <attributes>")

        # --- Read original attributes AND CALCULATE TRANSPOSED KEY ---
        original_key_elem = original_attributes_elem.find('.//key')
        original_fifths_text = "-2" # Default for Bb Major if missing
        original_key_mode = 'major' # Default mode
        if original_key_elem is not None:
            original_fifths_text = original_key_elem.findtext('fifths', original_fifths_text)
            original_key_mode = original_key_elem.findtext('mode', original_key_mode)
        else: print("    Warning: <key> element not found. Assuming original Bb Major (-2).")

        transposed_key_fifths = original_fifths_text # Default to original if conversion fails
        try:
            original_fifths_val = int(original_fifths_text)
            transposed_fifths_val = original_fifths_val + 1 # TRANSPOSE UP!
            transposed_key_fifths = str(transposed_fifths_val)
            print(f"    Transposing Key Signature: Original fifths={original_fifths_val} -> New fifths={transposed_fifths_val} ({original_key_mode})")
        except ValueError:
            print(f"    Warning: Could not parse original fifths value '{original_fifths_text}'. Key signature not transposed.")

        # Read other necessary attributes
        original_divisions = original_attributes_elem.findtext('.//divisions', '128')
        original_time_beats = original_attributes_elem.findtext('.//time/beats', '4')
        original_time_beat_type = original_attributes_elem.findtext('.//time/beat-type', '4')
        original_clef_sign = original_attributes_elem.findtext('.//clef/sign', 'G')
        original_clef_line = original_attributes_elem.findtext('.//clef/line', '2')
        # --- End Reading Attributes ---


        # --- Read original notes data ---
        original_notes_data = []
        # print("    Reading original notes from Measure 1...") # Less verbose
        for old_note in original_notes_elems:
             note_data = {'pitch_elem': None, 'rest_elem': None, 'duration_elem': None, 'type_elem': None}
             pitch = old_note.find('pitch'); rest = old_note.find('rest')
             if pitch is not None: note_data['pitch_elem'] = pitch
             elif rest is not None: note_data['rest_elem'] = rest
             if note_data['pitch_elem'] or note_data['rest_elem']:
                  note_data['duration_elem'] = old_note.find('duration')
                  note_data['type_elem'] = old_note.find('type')
                  if note_data['duration_elem'] is not None and note_data['type_elem'] is not None:
                       original_notes_data.append(note_data)
        # print(f"    Read {len(original_notes_data)} valid note/rest elements.")


        # --- Clear and Reconstruct Measure ---
        # print("    Clearing original Measure 1 content...") # Less verbose
        measure1.clear(); measure1.set('number', '1')
        if original_left_barline is not None: measure1.append(original_left_barline)

        # --- Add Reconstructed <attributes> using TRANSPOSED key ---
        # print("    Adding reconstructed <attributes>...") # Less verbose
        attributes_rebuilt = ET.Element('attributes')
        ET.SubElement(attributes_rebuilt, 'divisions').text = original_divisions
        key_rebuilt = ET.SubElement(attributes_rebuilt, 'key')
        ET.SubElement(key_rebuilt, 'fifths').text = transposed_key_fifths # USE TRANSPOSED VALUE
        ET.SubElement(key_rebuilt, 'mode').text = original_key_mode # Keep original mode
        time_rebuilt = ET.SubElement(attributes_rebuilt, 'time'); ET.SubElement(time_rebuilt, 'beats').text = original_time_beats; ET.SubElement(time_rebuilt, 'beat-type').text = original_time_beat_type
        clef_rebuilt = ET.SubElement(attributes_rebuilt, 'clef'); ET.SubElement(clef_rebuilt, 'sign').text = original_clef_sign; ET.SubElement(clef_rebuilt, 'line').text = original_clef_line
        measure1.append(attributes_rebuilt)

        # --- Add <print> element ---
        # print("    Adding <print> element...") # Less verbose
        print_elem = ET.Element('print'); sys_layout = ET.SubElement(print_elem, 'system-layout'); sys_margins = ET.SubElement(sys_layout, 'system-margins')
        ET.SubElement(sys_margins, 'left-margin').text = '50'; ET.SubElement(sys_margins, 'right-margin').text = '0'
        ET.SubElement(sys_layout, 'top-system-distance').text = '70'
        measure1.append(print_elem)

        # --- Add reconstructed <direction> for tempo ---
        # print("    Adding reconstructed <direction> with tempo...") # Less verbose
        direction_elem = ET.Element('direction', {'placement': 'above'}); dir_type = ET.SubElement(direction_elem, 'direction-type')
        metronome = ET.SubElement(dir_type, 'metronome', {'parentheses': 'no'}); ET.SubElement(metronome, 'beat-unit').text = 'quarter'; ET.SubElement(metronome, 'per-minute').text = '120'
        ET.SubElement(direction_elem, 'sound', {'tempo': '120'})
        measure1.append(direction_elem)

        # --- Re-add notes using READ data (same logic as before) ---
        # print("    Re-adding notes using READ original data and reference structure...") # Less verbose
        note_counter = 0; beam_level_1_state = None
        beamable_indices = set()
        if len(original_notes_data) > 3 and \
           original_notes_data[1].get('type_elem') is not None and original_notes_data[1]['type_elem'].text == 'eighth' and \
           original_notes_data[2].get('type_elem') is not None and original_notes_data[2]['type_elem'].text == 'eighth' and \
           original_notes_data[3].get('type_elem') is not None and original_notes_data[3]['type_elem'].text == 'eighth':
              beamable_indices = {1, 2, 3}

        for i, note_data in enumerate(original_notes_data):
            new_note = ET.Element('note')
            if note_data['rest_elem'] is not None:
                new_note.append(note_data['rest_elem']); beam_level_1_state = None
            elif note_data['pitch_elem'] is not None:
                new_note.append(note_data['pitch_elem'])
                ET.SubElement(new_note, 'voice').text = '1'
                step = note_data['pitch_elem'].findtext('step'); octave = int(note_data['pitch_elem'].findtext('octave', '4'))
                stem_dir = 'down' if octave > 4 or (octave == 4 and step == 'B') else 'up' # Adjusted stem logic slightly
                ET.SubElement(new_note, 'stem').text = stem_dir
                if i in beamable_indices:
                     if i == 1: ET.SubElement(new_note, 'beam', {'number': '1'}).text = 'begin'; beam_level_1_state = 'begin'
                     elif i == 2: ET.SubElement(new_note, 'beam', {'number': '1'}).text = 'continue'; beam_level_1_state = 'continue'
                     elif i == 3: ET.SubElement(new_note, 'beam', {'number': '1'}).text = 'end'; beam_level_1_state = None
                else: beam_level_1_state = None
            new_note.append(note_data['duration_elem']); new_note.append(note_data['type_elem'])
            measure1.append(new_note)
            note_counter += 1
        # print(f"    Re-added {note_counter} notes to Measure 1 from read data.")

        if original_right_barline is not None: measure1.append(original_right_barline)
        print("  Measure 1 rebuild complete.")


        # --- 7. Write Output ---
        tree.write(output_file, encoding='utf-8', xml_declaration=True, method='xml')
        print(f"\nSuccessfully wrote modified MusicXML to '{output_file}'")
        print(f"NOTE: KEY SIGNATURE TRANSPOSED UP one step to fifths={transposed_key_fifths} ({original_key_mode}).")
        print("      Pitches were NOT transposed. Applied general fixes & rebuilt Measure 1.")
        print("      Text content preserved (except M1 lyrics omitted).")
        print("      Try importing this file into Finale.")

    except ET.ParseError as e:
        print(f"Error parsing MusicXML file '{input_file}': {e}", file=sys.stderr)
        sys.exit(1)
    except FileNotFoundError:
        print(f"Error: Input file not found: '{input_file}'", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred during processing: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

# --- Main Execution ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Fixes MusicXML for Finale, transposes KEY SIGNATURE up one step, rebuilds Measure 1.")
    parser.add_argument("-f", "--from", dest="input_file", required=True,
                        help="Input MusicXML file (e.g., input.xml)")
    parser.add_argument("-t", "--to", dest="output_file", required=True,
                        help="Output MusicXML file for Finale (e.g., ouput.xml)")
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
         print(f"Error: Input file not found: {args.input_file}", file=sys.stderr)
         sys.exit(1)

    fix_transpose_key_rebuild_measure1(args.input_file, args.output_file)