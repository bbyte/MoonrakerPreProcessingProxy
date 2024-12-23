from pathlib import Path
import re

async def process(file_path: Path):
    """
    Preprocessing rule for OrcaSlicer multi-extruder files that:
    1. Removes M600 and T[n] commands before "filament start gcode" marker
    2. Removes standalone T[n] commands throughout the file
    3. Removes T[n] part from M104 and M109 commands
    
    Args:
        file_path: Path to the uploaded file
    """
    print(f"[INFO] OrcaSlicer multi-extruder rule processing file: {file_path}")
    
    if file_path.suffix.lower() not in ['.gcode', '.g']:
        print(f"[INFO] Skipping non-gcode file: {file_path}")
        return
        
    print(f"[INFO] Modifying G-code file: {file_path}")
    
    # Read the file content
    with open(file_path, 'rb') as f:
        content = f.read()
        
    # Convert to text for processing, keeping original line endings
    text_content = content.decode('utf-8')
    lines = text_content.splitlines(keepends=True)
    
    # Process the file
    found_filament_start = False
    modified_lines = []
    
    for line in lines:
        # Check for filament start marker
        if "filament start gcode" in line.lower():
            found_filament_start = True
            modified_lines.append(line)
            continue
            
        # Before filament start marker, remove M600 and T[n] commands
        if not found_filament_start:
            if re.match(r'^\s*(M600|T\d+)\s*$', line.strip()):
                continue
                
        # Process M104 and M109 commands - remove T[n] part if present
        if line.strip().startswith(('M104', 'M109')):
            # Remove T[n] part but keep the rest of the command
            line = re.sub(r'\bT\d+\s*', '', line)
        # Remove standalone T[n] commands
        elif re.match(r'^\s*T\d+\s*$', line.strip()):
            continue
            
        modified_lines.append(line)
    
    # Write modified content back to file
    with open(file_path, 'w', newline='') as f:
        f.writelines(modified_lines)
            
    print(f"[INFO] Successfully modified file: {file_path}")