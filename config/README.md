# Modified configs for the Qidi Q1 Pro

**Use at your own risk.**\
You actually need to place the steel build plate on the bed when it homes and probes. The aluminum bed will NOT trigger the inductive probe. Increase the Z offset way high if you're scared of damaging the build plate.

## Quick start TL;DR for advanced Klipper users
- `printer.cfg`: Replace everything except the SAVE_CONFIGS
- `gcode_macro.cfg`: Replace everything
- Start a print (with `PRINT_START HOTEND= BED= CHAMBER=`) (or call `GET_ZOFFSET` and use a paper or feeler guage) and adjust Z offset
- Issue `Z_OFFSET_APPLY_PROBE` to apply the Z offset. Z offset is cleared in subsequent `PRINT_START`
- Issue `Z_OFFSET_APPLY_ENDSTOP` to set endstop position, which affects where the nozzle sits relative to the bed before Z calibration

## Full Installation and First Use Guide
Please read it all before you start performing on your printer.

1. Back up the `gcode_macro.cfg` file, or just simply rename it.\
![image](https://github.com/user-attachments/assets/4d297ad7-567a-47a0-8136-7a97f89345bd)\
The `printer.cfg` file is automatically backed up by the system. You can download it or copy it to be extra safe.
2. Update the `printer.cfg` file. Select everything before `#*# <-- SAVE_CONFIG -->` and replace it with the file in this repo
    - Copy the contents of [printer.cfg](https://github.com/jrymk/q1pro-mods/blob/main/config/printer.cfg)\
    ![image](https://github.com/user-attachments/assets/0dcf031f-bc3a-4c0e-94b4-f012311969bd)
    - Select as shown below and paste\
    ![image](https://github.com/user-attachments/assets/909bafc3-a88e-4e24-8d62-c4353f6f0dd6)
    - Save\
    ![image](https://github.com/user-attachments/assets/448569d8-68e4-4d74-ab10-6f27dbab3420)
3. Create the new `gcode_macro.cfg` file
    - Add a new file and name it `gcode_macro.cfg`\
    ![image](https://github.com/user-attachments/assets/f4b473e7-7cc9-4680-91f3-9536e49c5a3e)
    ![image](https://github.com/user-attachments/assets/3a1518a7-cb4c-4111-b3af-99e0ad1d2c74)
    - Copy the contents of [gcode_macros.cfg](https://github.com/jrymk/q1pro-mods/blob/main/config/gcode_macro.cfg) file\
    ![image](https://github.com/user-attachments/assets/d3e90a53-9ae2-40dd-a5ea-86eebcdc4ce6)
    - Open the newly created file in the printer web interface and paste it in\
    ![image](https://github.com/user-attachments/assets/abd51b1c-b5e4-4513-9345-1cc2746a949b)
    - Save and Restart\
    ![image](https://github.com/user-attachments/assets/61e08dc9-aade-4b51-8042-495ecfda0432)
4. In theory, you may now send a print job. If you don't feel safe, set the Z offset way high, say 1mm, with the following command:
    ```
    SET_GCODE_OFFSET Z=1 MOVE=1
    ```
    after a print job with a large first layer area is sent. And you may use the printer display or the web interface to adjust the nozzle closer by using the "UP" arrow. If it is way high (which it should), you can use the same command with a smaller number to speed up the process, like `SET_GCODE_OFFSET Z=0.2 MOVE=1`.\
    ![image](https://github.com/user-attachments/assets/332b9816-2712-4a2b-9580-7efb32c77ded)
5. Also check if the nozzle cleaning works well on your printer and filament. **Check if the nozzle tip is clean**, and filament does not ooze during probing. If it does, drop the probing temperature, as shown below. This value is set high as the author does not print PLA at all, and this reduces the cooldown time before probing. Even if it doesn't ooze, try not to set it above 180 degrees as it may damage the build surface.
   Be extra sure that the nozzle looks nice and clean when calibrating your nozzle offset. If the nozzle is not clean during a print setup is fine, as the first layer will just be too high. But if you adjust the Z offset and save this result to the nozzle offset, subsequent prints will be too low, and **may damage your build plate!**\
    ![image](https://github.com/user-attachments/assets/5caef60d-2cf1-4e2c-8d08-36895e0d1e09)
6. After dialing the first layer, you may leave it printing, or cancel it. Type in `Z_OFFSET_APPLY_PROBE` to apply the adjustments you made with the Z offset to the nozzle probe, so the next time it will be perfect. By default, the Z offset you made are cleared when the next print job starts, so make sure to save it by issuing this command right now.
7. After that, you can also issue `Z_OFFSET_APPLY_ENDSTOP`, so the nozzle offset is about right even before any nozzle probing occurs. Still, try not to drive the bed near Z=0 before a print.
   ```
   Z_OFFSET_APPLY_PROBE
   Z_OFFSET_APPLY_ENDSTOP
   ```
   By default, the Z axis can go 1mm negative, to account for homing and probing variances. After you dial the endstop and nozzle offsets from my default "safe-ish" values, you may increase this number (to say -0.5mm or -0.2mm) to prevent disasters from happening. The -1 setting should prevent your bed and nozzles from permanently bending out of shape, since the bed is on springs, but you may further increase it to also save your build plate.
8. You may issue the `GET_ZOFFSET` command when the nozzle is clean to take a measurement of the endstop offset compared to the result from the last G28 home, without starting a print. And you can adjust the nozzle height with a piece of paper or a feeler guage and the Z offset controls to calibrate the nozzle height this way.

## Features
### Revamped Auto Z Offset
`Z_OFFSET_APPLY_ENDSTOP` (apply nozzle offset to endstop) updates the endstop position instead of the fixed -0.2 for the default Qidi config for an inductive, which makes no sense. It also requires `position_min: -4`, which may lead to a disaster.\
![image](https://github.com/user-attachments/assets/1495d940-6f27-40bf-980a-8ca75e65137c)

`Z_OFFSET_APPLY_PROBE` (apply babystep z offset to nozzle offset) updates the nozzle offset after a print finishes, applying the babystepping done during the print. This should not be done frequently, but when you do, it is easy to keep the results. The piezo sensors on the bed do not perfectly triggers when the nozzle contacts, probably due to flexes in the bed, insensitivity in the threshold circuitry, or some delay. Regardless, this value seems to be fairly consistent. This value is usually between 0.05mm and 0.1mm. To keep it safe, it will be at 0.1 by default. You may decrease the Z offset (using the up arrow) during a print to fine adjust it. Make sure the nozzle is clean during the nozzle probing, at least when first using these modified config files. Any positive value here should be all "safe", if the offset of the trigger point of the nozzle probe on your machine (usually less than 0.1mm) is less than your first layer Z height (usually greater than 0.1mm), then the nozzle will not dig into the build plate, ruining it. \
![image](https://github.com/user-attachments/assets/598aab2d-5fd3-4570-bcb4-3f7660671fbd)\
![image](https://github.com/user-attachments/assets/241d19f2-e812-4414-a0e7-1737ec18d5c2)

There is also an option to always apply the babystep offset to the nozzle. See more in `gcode_macros.cfg` `[gcode_macro JRYMK_MOD_VARIABLES]` `variable_keep_babystep_adjustments: 0/1`.

`GET_ZOFFSET` conditionally calibrates the bed sensor, probes with a nozzle, and will set the kinematic Z=0 position to the true zero. The probing position is randomized to prevent wear on the build plate, because although we are probing at a reduced nozzle temperature, I can still see wear marks on the bed from the default Qidi's configs with the fixed probing location.

