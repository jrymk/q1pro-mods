# Support for reading acceleration data from an adxl345 chip
#
# Copyright (C) 2020  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math, time, collections, multiprocessing, os
from . import bus, manual_probe, probe

# ADXL345 registers
REG_DEVID = 0x00
REG_BW_RATE = 0x2C
REG_POWER_CTL = 0x2D
REG_DATA_FORMAT = 0x31
REG_FIFO_CTL = 0x38
REG_MOD_READ = 0x80
REG_MOD_MULTI = 0x40
REG_THRESH_TAP = 0x1D
REG_DUR = 0x21
REG_INT_MAP = 0x2F
REG_TAP_AXES = 0x2A
REG_OFSX = 0x1E
REG_OFSY = 0x1F
REG_OFSZ = 0x20
REG_INT_ENABLE = 0x2E
REG_INT_SOURCE = 0x30

QUERY_RATES = {
    25: 0x8, 50: 0x9, 100: 0xa, 200: 0xb, 400: 0xc,
    800: 0xd, 1600: 0xe, 3200: 0xf,
}

ADXL345_DEV_ID = 0xe5

FREEFALL_ACCEL = 9.80665 * 1000.
SCALE = 0.0039 * FREEFALL_ACCEL # 3.9mg/LSB * Earth gravity in mm/s**2
DUR_SCALE = 0.000625 # 0.625 msec / LSB
TAP_SCALE = 0.0625 * FREEFALL_ACCEL # 62.5mg/LSB * Earth gravity in mm/s**2
OFS_SCALE = 0.0156 * FREEFALL_ACCEL # 15.6mg/LSB * Earth gravity in mm/s**2

PROBE_CALIBRATION_TIME = 1.
ADXL345_REST_TIME = .01

Accel_Measurement = collections.namedtuple(
    'Accel_Measurement', ('time', 'accel_x', 'accel_y', 'accel_z'))

# Sample results
class ADXL345Results:
    def __init__(self):
        self.raw_samples = None
        self.samples = []
        self.drops = self.overflows = 0
        self.time_per_sample = self.start_range = self.end_range = 0.
    def get_stats(self):
        return ("drops=%d,overflows=%d"
                ",time_per_sample=%.9f,start_range=%.6f,end_range=%.6f"
                % (self.drops, self.overflows,
                   self.time_per_sample, self.start_range, self.end_range))
    def setup_data(self, axes_map, raw_samples, end_sequence, overflows,
                   start1_time, start2_time, end1_time, end2_time):
        if not raw_samples or not end_sequence:
            return
        self.axes_map = axes_map
        self.raw_samples = raw_samples
        self.overflows = overflows
        self.start2_time = start2_time
        self.start_range = start2_time - start1_time
        self.end_range = end2_time - end1_time
        self.total_count = (end_sequence - 1) * 8 + len(raw_samples[-1][1]) // 6
        total_time = end2_time - start2_time
        self.time_per_sample = time_per_sample = total_time / self.total_count
        self.seq_to_time = time_per_sample * 8.
        actual_count = sum([len(data)//6 for _, data in raw_samples])
        self.drops = self.total_count - actual_count
    def decode_samples(self):
        if not self.raw_samples:
            return self.samples
        (x_pos, x_scale), (y_pos, y_scale), (z_pos, z_scale) = self.axes_map
        actual_count = 0
        self.samples = samples = [None] * self.total_count
        for seq, data in self.raw_samples:
            d = bytearray(data)
            count = len(data)
            sdata = [(d[i] | (d[i+1] << 8)) - ((d[i+1] & 0x80) << 9)
                     for i in range(0, count-1, 2)]
            seq_time = self.start2_time + seq * self.seq_to_time
            for i in range(count//6):
                samp_time = seq_time + i * self.time_per_sample
                x = sdata[i*3 + x_pos] * x_scale
                y = sdata[i*3 + y_pos] * y_scale
                z = sdata[i*3 + z_pos] * z_scale
                samples[actual_count] = Accel_Measurement(samp_time, x, y, z)
                actual_count += 1
        del samples[actual_count:]
        return self.samples
    def write_to_file(self, filename):
        def write_impl():
            try:
                # Try to re-nice writing process
                os.nice(20)
            except:
                pass
            f = open(filename, "w")
            f.write("##%s\n#time,accel_x,accel_y,accel_z\n" % (
                self.get_stats(),))
            samples = self.samples or self.decode_samples()
            for t, accel_x, accel_y, accel_z in samples:
                f.write("%.6f,%.6f,%.6f,%.6f\n" % (
                    t, accel_x, accel_y, accel_z))
            f.close()
        write_proc = multiprocessing.Process(target=write_impl)
        write_proc.daemon = True
        write_proc.start()

class BedOffsetHelper:
    def __init__(self, config):
        self.printer = config.get_printer()
        # Register BED_OFFSET_CALIBRATE command
        zconfig = config.getsection('stepper_z')
        self.z_position_endstop = zconfig.getfloat('position_endstop', None,
                                                   note_valid=False)
        if self.z_position_endstop is None:
            return
        self.bed_probe_point = None
        if config.get('bed_probe_point', None) is not None:
            try:
                self.bed_probe_point = [
                        float(coord.strip()) for coord in
                        config.get('bed_probe_point').split(',', 1)]
            except:
                raise config.error(
                        "Unable to parse bed_probe_point '%s'" % (
                            config.get('bed_probe_point')))
            self.horizontal_move_z = config.getfloat(
                    'horizontal_move_z', 5.)
            self.horizontal_move_speed = config.getfloat(
                    'horizontal_move_speed', 50., above=0.)
        gcode = self.printer.lookup_object('gcode')
        gcode.register_command(
            'BED_OFFSET_CALIBRATE', self.cmd_BED_OFFSET_CALIBRATE,
            desc=self.cmd_BED_OFFSET_CALIBRATE_help)
    def bed_offset_finalize(self, pos, gcmd):
        if pos is None:
            return
        z_pos = self.z_position_endstop - pos[2]
        gcmd.respond_info(
            "stepper_z: position_endstop: %.3f\n"
            "The SAVE_CONFIG command will update the printer config file\n"
            "with the above and restart the printer." % (z_pos,))
        configfile = self.printer.lookup_object('configfile')
        configfile.set('stepper_z', 'position_endstop', "%.3f" % (z_pos,))
    cmd_BED_OFFSET_CALIBRATE_help = "Calibrate a bed offset using ADXL345 probe"
    def cmd_BED_OFFSET_CALIBRATE(self, gcmd):
        manual_probe.verify_no_manual_probe(self.printer)
        probe = self.printer.lookup_object('probe')
        lift_speed = probe.get_lift_speed(gcmd)
        toolhead = self.printer.lookup_object('toolhead')
        oldpos = toolhead.get_position()
        if self.bed_probe_point is not None:
            toolhead.manual_move([None, None, self.horizontal_move_z],
                                 lift_speed)
            toolhead.manual_move(self.bed_probe_point + [None],
                                 self.horizontal_move_speed)
        curpos = probe.run_probe(gcmd)
        offset_pos = [0., 0., curpos[2] - probe.get_offsets()[2]]
        if self.bed_probe_point is not None:
            curpos[2] = self.horizontal_move_z
        else:
            curpos[2] = oldpos[2]
        toolhead.manual_move(curpos, lift_speed)
        self.bed_offset_finalize(offset_pos, gcmd)

# ADXL345 virtual endstop wrapper for probing
class ADXL345EndstopWrapper:
    def __init__(self, config, adxl345, axes_map):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:connect", self.calibrate)
        self.calibrated = False
        self.adxl345 = adxl345
        self.axes_map = axes_map
        self.ofs_regs = (REG_OFSX, REG_OFSY, REG_OFSZ)
        int_pin = config.get('int_pin').strip()
        self.inverted = False
        if int_pin.startswith('!'):
            self.inverted = True
            int_pin = int_pin[1:].strip()
        if int_pin != 'int1' and int_pin != 'int2':
            raise config.error('int_pin must specify one of int1 or int2 pins')
        self.int_map = 0x40 if int_pin == 'int2' else 0x0
        probe_pin = config.get('probe_pin')
        self.position_endstop = config.getfloat('z_offset')
        self.tap_thresh = config.getfloat('tap_thresh', 5000,
                                          minval=TAP_SCALE, maxval=100000.)
        self.tap_dur = config.getfloat('tap_dur', 0.01,
                                       above=DUR_SCALE, maxval=0.1)
        self.next_cmd_time = self.action_end_time = 0.
        # Create an "endstop" object to handle the sensor pin
        ppins = self.printer.lookup_object('pins')
        pin_params = ppins.lookup_pin(probe_pin, can_invert=True,
                                      can_pullup=True)
        mcu = pin_params['chip']
        mcu.register_config_callback(self._build_config)
        self.mcu_endstop = mcu.setup_pin('endstop', pin_params)
        # Wrappers
        self.get_mcu = self.mcu_endstop.get_mcu
        self.add_stepper = self.mcu_endstop.add_stepper
        self.get_steppers = self.mcu_endstop.get_steppers
        self.home_start = self.mcu_endstop.home_start
        self.home_wait = self.mcu_endstop.home_wait
        self.query_endstop = self.mcu_endstop.query_endstop
        # Register commands
        gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command(
                "ACCEL_PROBE_CALIBRATE", "CHIP", None,
                self.cmd_ACCEL_PROBE_CALIBRATE,
                desc=self.cmd_ACCEL_PROBE_CALIBRATE_help)
        gcode.register_mux_command(
                "SET_ACCEL_PROBE", "CHIP", None, self.cmd_SET_ACCEL_PROBE,
                desc=self.cmd_SET_ACCEL_PROBE_help)
        # Register bed offset calibration helper
        BedOffsetHelper(config)
    def _build_config(self):
        kin = self.printer.lookup_object('toolhead').get_kinematics()
        for stepper in kin.get_steppers():
            if stepper.is_active_axis('z'):
                self.add_stepper(stepper)
    def calibrate(self, gcmd=None, retries=3):
        adxl345 = self.adxl345
        if not adxl345.is_initialized():
            # ADXL345 that works as a probe must be initialized from the start
            adxl345.initialize()
        adxl345.set_reg(REG_POWER_CTL, 0x00)
        if self.inverted:
            adxl345.set_reg(REG_DATA_FORMAT, 0x2B)
        adxl345.set_reg(REG_INT_MAP, self.int_map)
        adxl345.set_reg(REG_TAP_AXES, 0x7)
        adxl345.set_reg(REG_THRESH_TAP, int(self.tap_thresh / TAP_SCALE))
        adxl345.set_reg(REG_DUR, int(self.tap_dur / DUR_SCALE))
        # Offset freefall accleration on the true Z axis
        for reg in self.ofs_regs:
            adxl345.set_reg(reg, 0x00)
        adxl345.start_measurements()
        reactor = self.printer.get_reactor()
        reactor.register_callback(lambda ev: self._offset_axes(gcmd, retries),
                                  reactor.monotonic() + PROBE_CALIBRATION_TIME)
    def _offset_axes(self, gcmd, retries):
        res = self.adxl345.finish_measurements()
        msg_func = gcmd.respond_info if gcmd is not None else logging.info
        samples = res.decode_samples()
        x_ofs = sum([s.accel_x for s in samples]) / len(samples)
        y_ofs = sum([s.accel_y for s in samples]) / len(samples)
        z_ofs = sum([s.accel_z for s in samples]) / len(samples)
        meas_freefall_accel = math.sqrt(x_ofs**2 + y_ofs**2 + z_ofs**2)
        if abs(meas_freefall_accel - FREEFALL_ACCEL) > FREEFALL_ACCEL * 0.5:
            err_msg = ("Calibration error: ADXL345 incorrectly measures "
                       "freefall accleration: %.0f (measured) vs %.0f "
                       "(expected)" % (meas_freefall_accel, FREEFALL_ACCEL))
            if retries > 0:
                msg_func(err_msg + ", retrying (%d)" % (retries-1,))
                self.calibrate(gcmd, retries-1)
            else:
                msg_func(err_msg + ", aborting self-calibration")
            return
        x_m = max([abs(s.accel_x - x_ofs) for s in samples])
        y_m = max([abs(s.accel_y - y_ofs) for s in samples])
        z_m = max([abs(s.accel_z - z_ofs) for s in samples])
        accel_noise = max(x_m, y_m, z_m)
        if accel_noise > self.tap_thresh:
            err_msg = ("Calibration error: ADXL345 noise level too high for "
                       "the configured tap_thresh: %.0f (tap_thresh) vs "
                       "%.0f (noise)" % (self.tap_thresh, accel_noise))
            if retries > 0:
                msg_func(err_msg + ", retrying (%d)" % (retries-1,))
                self.calibrate(gcmd, retries-1)
            else:
                msg_func(err_msg + ", aborting self-calibration")
            return
        for ofs, axis in zip((x_ofs, y_ofs, z_ofs), (0, 1, 2)):
            ofs_reg = self.ofs_regs[self.axes_map[axis][0]]
            ofs_val = 0xFF & int(round(
                -ofs / self.axes_map[axis][1] * (SCALE / OFS_SCALE)))
            self.adxl345.set_reg(ofs_reg, ofs_val)
        msg_func("Successfully calibrated ADXL345")
        self.calibrated = True
    def multi_probe_begin(self):
        pass
    def multi_probe_end(self):
        pass
    def _try_clear_tap(self):
        adxl345 = self.adxl345
        tries = 8
        while tries > 0:
            val = adxl345.read_reg(REG_INT_SOURCE)
            if not (val & 0x40):
                return True
            tries -= 1
        return False
    def probe_prepare(self, hmove):
        if not self.calibrated:
            raise self.printer.command_error(
                    "ADXL345 probe failed calibration, "
                    "retry with ACCEL_PROBE_CALIBRATE command")
        adxl345 = self.adxl345
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.flush_step_generation()
        print_time = toolhead.get_last_move_time()
        clock = self.adxl345.get_mcu().print_time_to_clock(print_time +
                                                           ADXL345_REST_TIME)
        if not adxl345.is_initialized():
            adxl345.initialize()
        adxl345.set_reg(REG_INT_ENABLE, 0x00, minclock=clock)
        adxl345.read_reg(REG_INT_SOURCE)
        adxl345.set_reg(REG_INT_ENABLE, 0x40, minclock=clock)
        if not adxl345.is_measuring():
            adxl345.set_reg(REG_POWER_CTL, 0x08, minclock=clock)
        if not self._try_clear_tap():
            raise self.printer.command_error(
                    "ADXL345 tap triggered before move, too sensitive?")
    def probe_finish(self, hmove):
        adxl345 = self.adxl345
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.dwell(ADXL345_REST_TIME)
        print_time = toolhead.get_last_move_time()
        clock = adxl345.get_mcu().print_time_to_clock(print_time)
        adxl345.set_reg(REG_INT_ENABLE, 0x00, minclock=clock)
        if not adxl345.is_measuring():
            adxl345.set_reg(REG_POWER_CTL, 0x00)
        if not self._try_clear_tap():
            raise self.printer.command_error(
                    "ADXL345 tap triggered after move, too sensitive?")
    cmd_ACCEL_PROBE_CALIBRATE_help = "Force ADXL345 probe [re-]calibration"
    def cmd_ACCEL_PROBE_CALIBRATE(self, gcmd):
        self.calibrate(gcmd)
    cmd_SET_ACCEL_PROBE_help = "Configure ADXL345 parameters related to probing"
    def cmd_SET_ACCEL_PROBE(self, gcmd):
        self.tap_thresh = gcmd.get_float('TAP_THRESH', self.tap_thresh,
                                         minval=TAP_SCALE, maxval=100000.)
        self.tap_dur = config.getfloat('TAP_DUR', self.tap_dur,
                                       above=DUR_SCALE, maxval=0.1)
        adxl345.set_reg(REG_THRESH_TAP, int(self.tap_thresh / TAP_SCALE))
        adxl345.set_reg(REG_DUR, int(self.tap_dur / DUR_SCALE))

# Printer class that controls ADXL345 chip
class ADXL345:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.query_rate = 0
        self.last_tx_time = 0.
        self.config = config
        am = {'x': (0, SCALE), 'y': (1, SCALE), 'z': (2, SCALE),
              '-x': (0, -SCALE), '-y': (1, -SCALE), '-z': (2, -SCALE)}
        axes_map = config.get('axes_map', 'x,y,z').split(',')
        if len(axes_map) != 3 or any([a.strip() not in am for a in axes_map]):
            raise config.error("Invalid adxl345 axes_map parameter")
        self.axes_map = [am[a.strip()] for a in axes_map]
        self.data_rate = config.getint('rate', 3200)
        if self.data_rate not in QUERY_RATES:
            raise config.error("Invalid rate parameter: %d" % (self.data_rate,))
        # Measurement storage (accessed from background thread)
        self.raw_samples = []
        self.last_sequence = 0
        self.samples_start1 = self.samples_start2 = 0.
        # Setup mcu sensor_adxl345 bulk query code
        self.spi = bus.MCU_SPI_from_config(config, 3, default_speed=5000000)
        self.mcu = mcu = self.spi.get_mcu()
        self.oid = oid = mcu.create_oid()
        self.query_adxl345_cmd = self.query_adxl345_end_cmd =None
        mcu.add_config_cmd("config_adxl345 oid=%d spi_oid=%d"
                           % (oid, self.spi.get_oid()))
        mcu.add_config_cmd("query_adxl345 oid=%d clock=0 rest_ticks=0"
                           % (oid,), on_restart=True)
        mcu.register_config_callback(self._build_config)
        mcu.register_response(self._handle_adxl345_start, "adxl345_start", oid)
        mcu.register_response(self._handle_adxl345_data, "adxl345_data", oid)
        # Register commands
        self.name = "default"
        if len(config.get_name().split()) > 1:
            self.name = config.get_name().split()[1]
        gcode = self.printer.lookup_object('gcode')
        gcode.register_mux_command("ACCELEROMETER_MEASURE", "CHIP", self.name,
                                   self.cmd_ACCELEROMETER_MEASURE,
                                   desc=self.cmd_ACCELEROMETER_MEASURE_help)
        gcode.register_mux_command("ACCELEROMETER_QUERY", "CHIP", self.name,
                                   self.cmd_ACCELEROMETER_QUERY,
                                   desc=self.cmd_ACCELEROMETER_QUERY_help)
        gcode.register_mux_command("ADXL345_DEBUG_READ", "CHIP", self.name,
                                   self.cmd_ADXL345_DEBUG_READ,
                                   desc=self.cmd_ADXL345_DEBUG_READ_help)
        gcode.register_mux_command("ADXL345_DEBUG_WRITE", "CHIP", self.name,
                                   self.cmd_ADXL345_DEBUG_WRITE,
                                   desc=self.cmd_ADXL345_DEBUG_WRITE_help)
        gcode.register_mux_command("TEST_MYCMD", "CHIP", self.name,
                                   self.cmd_TEST_MYCMD,
                                   desc=self.cmd_TEST_MYCMD_help)
        gcode.register_mux_command("MKS_PROBE", "CHIP", self.name,
                                    self.cmd_MKS_PROBE,
                                    desc=self.cmd_MKS_PROBE_help)
        if self.name == "default":
            gcode.register_mux_command("ACCELEROMETER_MEASURE", "CHIP", None,
                                       self.cmd_ACCELEROMETER_MEASURE)
            gcode.register_mux_command("ACCELEROMETER_QUERY", "CHIP", None,
                                       self.cmd_ACCELEROMETER_QUERY)
            gcode.register_mux_command("ADXL345_DEBUG_READ", "CHIP", None,
                                       self.cmd_ADXL345_DEBUG_READ,
                                       desc=self.cmd_ADXL345_DEBUG_READ_help)
            gcode.register_mux_command("ADXL345_DEBUG_WRITE", "CHIP", None,
                                       self.cmd_ADXL345_DEBUG_WRITE,
                                       desc=self.cmd_ADXL345_DEBUG_WRITE_help)
            gcode.register_mux_command("TEST_MYCMD", "CHIP", None,
                                       self.cmd_TEST_MYCMD,
                                       desc=self.cmd_TEST_MYCMD_help)
            gcode.register_mux_command("MKS_PROBE", "CHIP", None,
                                       self.cmd_MKS_PROBE,
                                       desc=self.cmd_MKS_PROBE_help)
                                    
        self.adxl345_endstop = ADXL345EndstopWrapper(self.config, self, self.axes_map)
    cmd_MKS_PROBE_help = "test my cmd"
    def cmd_MKS_PROBE(self, gcmd):
        gcmd.respond_info("go to mks Probe success")
        self.printer.remove_object('probe')
        self.printer.lookup_object('gcode').remove_command('PROBE')
        self.printer.lookup_object('gcode').remove_command('QUERY_PROBE')
        self.printer.lookup_object('gcode').remove_command('PROBE_CALIBRATE')
        self.printer.lookup_object('gcode').remove_command('PROBE_ACCURACY')
        self.printer.lookup_object('gcode').remove_command('Z_OFFSET_APPLY_PROBE')
        self.printer.lookup_object('gcode').remove_command('MKS_SHOW_Z_OFFSET')
        self.printer.lookup_object('pins').remove_chip('probe')
        self.printer.add_object('probe', probe.load_config(self.probe_config))
        # self.printer.lookup_object('probe').multi_probe_end()
    cmd_TEST_MYCMD_help = "test my cmd"
    def cmd_TEST_MYCMD(self, gcmd):
        gcmd.respond_info("TEST MY CMD success")
        # if config.get('probe_pin', None) is not None:
        #     adxl345_endstop = ADXL345EndstopWrapper(config, self, self.axes_map)
        self.probe_config = self.printer.lookup_object('probe').config
        # self.printer.add_object('probebak', None)
        # self.printer.copy_object('probe', 'probebak')
        self.printer.remove_object('probe')
        self.printer.lookup_object('gcode').remove_command('PROBE')
        self.printer.lookup_object('gcode').remove_command('QUERY_PROBE')
        self.printer.lookup_object('gcode').remove_command('PROBE_CALIBRATE')
        self.printer.lookup_object('gcode').remove_command('PROBE_ACCURACY')
        self.printer.lookup_object('gcode').remove_command('Z_OFFSET_APPLY_PROBE')
        self.printer.lookup_object('gcode').remove_command('MKS_SHOW_Z_OFFSET')
        self.printer.lookup_object('pins').remove_chip('probe')
        self.printer.add_object('probe', probe.PrinterProbe(self.config, self.adxl345_endstop))
    def is_initialized(self):
        # In case of miswiring, testing ADXL345 device ID prevents treating
        # noise or wrong signal as a correctly initialized device
        return (self.read_reg(REG_DEVID) == ADXL345_DEV_ID and
                (self.read_reg(REG_DATA_FORMAT) & 0xB) != 0)
    def initialize(self):
        # Setup ADXL345 parameters and verify chip connectivity
        self.set_reg(REG_POWER_CTL, 0x00)
        dev_id = self.read_reg(REG_DEVID)
        if dev_id != ADXL345_DEV_ID:
            raise self.printer.command_error("Invalid adxl345 id (got %x vs %x)"
                                             % (dev_id, ADXL345_DEV_ID))
        self.set_reg(REG_DATA_FORMAT, 0x0B)
    def get_mcu(self):
        return self.spi.get_mcu()
    def _build_config(self):
        self.query_adxl345_cmd = self.mcu.lookup_command(
            "query_adxl345 oid=%c clock=%u rest_ticks=%u",
            cq=self.spi.get_command_queue())
        self.query_adxl345_end_cmd = self.mcu.lookup_query_command(
            "query_adxl345 oid=%c clock=%u rest_ticks=%u",
            "adxl345_end oid=%c end1_clock=%u end2_clock=%u"
            " limit_count=%hu sequence=%hu",
            oid=self.oid, cq=self.spi.get_command_queue())
    def _clock_to_print_time(self, clock):
        return self.mcu.clock_to_print_time(self.mcu.clock32_to_clock64(clock))
    def _handle_adxl345_start(self, params):
        self.samples_start1 = self._clock_to_print_time(params['start1_clock'])
        self.samples_start2 = self._clock_to_print_time(params['start2_clock'])
    def _handle_adxl345_data(self, params):
        last_sequence = self.last_sequence
        sequence = (last_sequence & ~0xffff) | params['sequence']
        if sequence < last_sequence:
            sequence += 0x10000
        self.last_sequence = sequence
        raw_samples = self.raw_samples
        if len(raw_samples) >= 300000:
            # Avoid filling up memory with too many samples
            return
        raw_samples.append((sequence, params['data']))
    def _convert_sequence(self, sequence):
        sequence = (self.last_sequence & ~0xffff) | sequence
        if sequence < self.last_sequence:
            sequence += 0x10000
        return sequence
    def read_reg(self, reg):
        params = self.spi.spi_transfer([reg | REG_MOD_READ, 0x00])
        response = bytearray(params['response'])
        return response[1]
    def set_reg(self, reg, val, minclock=0):
        self.spi.spi_send([reg, val & 0xFF], minclock=minclock)
        stored_val = self.read_reg(reg)
        if stored_val != val:
            raise self.printer.command_error(
                    "Failed to set ADXL345 register [0x%x] to 0x%x: got 0x%x. "
                    "This is generally indicative of connection problems "
                    "(e.g. faulty wiring) or a faulty adxl345 chip." % (
                        reg, val, stored_val))
    def is_measuring(self):
        return self.query_rate > 0
    def start_measurements(self, rate=None):
        if self.is_measuring():
            return
        rate = rate or self.data_rate
        if not self.is_initialized():
            self.initialize()
        # Setup chip in requested query rate
        clock = 0
        if self.last_tx_time:
            clock = self.mcu.print_time_to_clock(self.last_tx_time)
        self.set_reg(REG_POWER_CTL, 0x00, minclock=clock)
        self.set_reg(REG_FIFO_CTL, 0x00)
        self.set_reg(REG_BW_RATE, QUERY_RATES[rate])
        self.set_reg(REG_FIFO_CTL, 0x80)
        # Setup samples
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        self.raw_samples = []
        self.last_sequence = 0
        self.samples_start1 = self.samples_start2 = print_time
        # Start bulk reading
        reqclock = self.mcu.print_time_to_clock(print_time)
        rest_ticks = self.mcu.seconds_to_clock(4. / rate)
        self.last_tx_time = print_time
        self.query_rate = rate
        self.query_adxl345_cmd.send([self.oid, reqclock, rest_ticks],
                                    reqclock=reqclock)
    def finish_measurements(self):
        if not self.is_measuring():
            return ADXL345Results()
        # Halt bulk reading
        print_time = self.printer.lookup_object('toolhead').get_last_move_time()
        clock = self.mcu.print_time_to_clock(print_time)
        params = self.query_adxl345_end_cmd.send([self.oid, 0, 0],
                                                 minclock=clock)
        self.last_tx_time = print_time
        self.query_rate = 0
        raw_samples = self.raw_samples
        self.raw_samples = []
        # Generate results
        end1_time = self._clock_to_print_time(params['end1_clock'])
        end2_time = self._clock_to_print_time(params['end2_clock'])
        end_sequence = self._convert_sequence(params['sequence'])
        overflows = params['limit_count']
        res = ADXL345Results()
        res.setup_data(self.axes_map, raw_samples, end_sequence, overflows,
                       self.samples_start1, self.samples_start2,
                       end1_time, end2_time)
        logging.info("ADXL345 finished %d measurements: %s",
                     res.total_count, res.get_stats())
        return res
    def end_query(self, name, gcmd):
        if not self.is_measuring():
            return
        res = self.finish_measurements()
        # Write data to file
        if self.name == "default":
            filename = "/tmp/adxl345-%s.csv" % (name,)
        else:
            filename = "/tmp/adxl345-%s-%s.csv" % (self.name, name,)
        res.write_to_file(filename)
        gcmd.respond_info(
                "Writing raw accelerometer data to %s file" % (filename,))
    cmd_ACCELEROMETER_MEASURE_help = "Start/stop accelerometer"
    def cmd_ACCELEROMETER_MEASURE(self, gcmd):
        if self.is_measuring():
            name = gcmd.get("NAME", time.strftime("%Y%m%d_%H%M%S"))
            if not name.replace('-', '').replace('_', '').isalnum():
                raise gcmd.error("Invalid adxl345 NAME parameter")
            self.end_query(name, gcmd)
            gcmd.respond_info("adxl345 measurements stopped")
        else:
            rate = gcmd.get_int("RATE", self.data_rate)
            if rate not in QUERY_RATES:
                raise gcmd.error("Not a valid adxl345 query rate: %d" % (rate,))
            self.start_measurements(rate)
            gcmd.respond_info("adxl345 measurements started")
    cmd_ACCELEROMETER_QUERY_help = "Query accelerometer for the current values"
    def cmd_ACCELEROMETER_QUERY(self, gcmd):
        if self.is_measuring():
            raise gcmd.error("adxl345 measurements in progress")
        self.start_measurements()
        reactor = self.printer.get_reactor()
        eventtime = starttime = reactor.monotonic()
        while not self.raw_samples:
            eventtime = reactor.pause(eventtime + .1)
            if eventtime > starttime + 3.:
                # Try to shutdown the measurements
                self.finish_measurements()
                raise gcmd.error("Timeout reading adxl345 data")
        result = self.finish_measurements()
        values = result.decode_samples()
        _, accel_x, accel_y, accel_z = values[-1]
        gcmd.respond_info("adxl345 values (x, y, z): %.6f, %.6f, %.6f" % (
            accel_x, accel_y, accel_z))
    cmd_ADXL345_DEBUG_READ_help = "Query accelerometer register (for debugging)"
    def cmd_ADXL345_DEBUG_READ(self, gcmd):
        if self.is_measuring():
            raise gcmd.error("adxl345 measurements in progress")
        reg = gcmd.get("REG", minval=29, maxval=57, parser=lambda x: int(x, 0))
        val = self.read_reg(reg)
        gcmd.respond_info("ADXL345 REG[0x%x] = 0x%x" % (reg, val))
    cmd_ADXL345_DEBUG_WRITE_help = "Set accelerometer register (for debugging)"
    def cmd_ADXL345_DEBUG_WRITE(self, gcmd):
        if self.is_measuring():
            raise gcmd.error("adxl345 measurements in progress")
        reg = gcmd.get("REG", minval=29, maxval=57, parser=lambda x: int(x, 0))
        val = gcmd.get("VAL", minval=0, maxval=255, parser=lambda x: int(x, 0))
        self.set_reg(reg, val)

def load_config(config):
    return ADXL345(config)

def load_config_prefix(config):
    return ADXL345(config)
