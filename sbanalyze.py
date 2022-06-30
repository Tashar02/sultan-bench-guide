#!/usr/bin/env python

#
# SBanalyze
#
# This program analyzes sultan_bench result logs. It produces data tables,
# stats, and EAS core costs if the analysis is successful.
#

#
# Credits
#
# @kerneltoast: sultan_bench, formulas, logic, and overall guidance
# @RenderBroken: help with the EAS portion and general sanity checking
# @nysadev: inspiration for adding cap-power energy model support
# @lazerl0rd: help with the statistics aspects of the program
# @kenny3fcb: providing data from sdm636 and sdm660 SoCs
# ARM: excellent documentation about EAS and energy models
#

#
# Licensed under the MIT License (MIT)
#
# Copyright (c) 2019 Danny Lin <danny@kdrag0n.dev>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#

import argparse
import itertools
import operator
import os
import re
import statistics
import sys
import textwrap

current_line_num = 0

SCHED_CAPACITY_SCALE = 1024

DT_ROOT_HEADER = '''
/ {
'''
DT_CPU_CORE_HEADER = '''
&CPU{0} {{
'''
DT_CPU_CORE_FOOTER = '''};
'''
DT_EM_HEADER = '''\tenergy_costs: energy-costs {
\t\tcompatible = "sched-energy";
'''
DT_EM_COSTS_HEADER = '''
\t\t{0}_COST_{2}: {1}-cost{2} {{
\t\t\tbusy-cost-data = <
'''
DT_EM_COSTS_FOOTER = '''\t\t\t>;
\t\t\tidle-cost-data = <
\t\t\t\t
\t\t\t>;
\t\t};
'''
DT_EM_FOOTER ='''\t}; /* energy-costs */
'''
DT_ROOT_FOOTER = '''};
'''

# Regexes used for parsing
LOG_START_REGEX = re.compile(r'sultan_bench: START: CPU(\d+): \[\s*(\d+) kHz\]')
LOG_POWER_REGEX = re.compile(r'sultan_bench: power usage \[\s*(\d+) mW\]')
LOG_STOP_REGEX = re.compile(r'sultan_bench: STOP: CPU(\d+): \[\s*(\d+) kHz\] \[\s*(\d+) us\]')

INFO_BEGIN = '\x1b[1;32m'
INFO_END = '\x1b[0m'
ERROR_BEGIN = '\x1b[1;31m'
ERROR_END = '\x1b[0m'


### Helpers ###

def log_header(message):
    print(f'{INFO_BEGIN}{message}{INFO_END}')

def log_item(message):
    print(f'    • {message}')

def log_error(cluster, message):
    print(f'Cluster {cluster}: {ERROR_BEGIN}{message}{ERROR_END}', file=sys.stderr)

def compare_by_eff(first_time_us):
    def comparator(vals):
        power_mw, time_us = vals[1]
        return power_mw * time_us / first_time_us

    return comparator

def remove_indices_from_list(val_list, idx_list):
    for idx in sorted(idx_list, reverse=True):
        del val_list[idx]

    return val_list

def get_midrange(values):
    # Get mean and stddev
    mean = statistics.mean(values)
    stddev = statistics.stdev(values)

    # Locate outliers (i.e. delta from mean > stddev * 1.5)
    to_remove = []
    threshold = stddev * 1.5
    for idx, val in enumerate(values):
        delta = abs(val - mean)
        if delta > threshold:
            to_remove.append(idx)

    # Remove the outliers
    remove_indices_from_list(values, to_remove)

    # Calculate midrange now that outliers have been removed
    _min = min(values)
    _max = max(values)
    return (_min + _max) / 2

### Cluster data processing ###

def parse_log(data_tbl, in_file, out_file):
    global current_line_num

    # Initialize data containers and active flag
    cur_freq = 0
    freq_pwr_list = []
    freq_time_list = []
    is_benching = False
    cores = 0
    count_cores = True

    # Define helper to finish freqs because we need to invoke it at the end as well
    def finish_freq():
        if cur_freq:
            if freq_pwr_list and freq_time_list:
                power_mw_mid = get_midrange(freq_pwr_list)
                time_us_med = statistics.median(freq_time_list)
                data_tbl[cur_freq] = (power_mw_mid, time_us_med)

                out_file.write(f'  - Midrange power usage: {power_mw_mid} mW\n')
                out_file.write(f'  - Median performance: {time_us_med} μs\n')
            else:
                out_file.write(f'  * Ignored incomplete frequency: {freq_khz} kHz\n')

    # Read the input file, line by line
    for line in in_file:
        current_line_num += 1

        if 'START' in line:
            # Match regex to extract values
            match = LOG_START_REGEX.search(line)
            if not match:
                out_file.write(f'  * Ignoring malformed START line: "{line}"\n')

            # Get values from match
            cpu_num = int(match.group(1))
            freq_khz = int(match.group(2))

            # Increment core counter if counting
            if count_cores:
                cores += 1

            # Skip if already switched (each core prints a START line)
            if freq_khz == cur_freq:
                continue

            # Finish off the previous freq because now we know it's done for good
            finish_freq()

            # We're starting to bench a new freq; clear data containers in preparation
            # and set active flag
            cur_freq = freq_khz
            freq_pwr_list = []
            freq_time_list = []
            is_benching = True

            # Write freq header to log
            out_file.write(f'\nFrequency: {cur_freq} kHz\n')
        elif 'power usage' in line:
            # Match regex to extract value
            match = LOG_POWER_REGEX.search(line)
            if not match:
                out_file.write(f'  * Ignoring malformed power usage line: "{line}"\n')

            # Get value from match
            power_mw = int(match.group(1))

            if cur_freq and is_benching:
                # Value came while benching; record it
                freq_pwr_list.append(power_mw)
            else:
                # Encountered power value while not actively benching
                # This is normal because the power readings come from a separate thread; ignore and move on
                out_file.write(f'  * Ignored stray power value: {power_mw} mW\n')
        elif 'STOP' in line:
            # Match regex to extract values
            match = LOG_STOP_REGEX.search(line)
            if not match:
                out_file.write(f'  * Ignoring malformed STOP line: "{line}"\n')

            # Get values from match
            cpu_num = int(match.group(1))
            freq_khz = int(match.group(2))
            time_us = int(match.group(3))

            if cur_freq != freq_khz:
                # Stopped freq is NOT the freq we're currently benching; warn and move on
                out_file.write(f'  * Ignored performance value ({time_us} μs) for {freq_khz} kHz\n')
                out_file.write('      * There may be synchronization issues')
            elif cur_freq:
                # Stopped freq matches current freq; record the time and ignore further power values
                count_cores = False
                freq_time_list.append(time_us)
                is_benching = False
            else:
                # Encountered STOP line before we started benching a freq; warn and move on
                out_file.write(f'  * Ignored stray performance value: {time_us} μs\n')
                out_file.write('      * Log may be incomplete\n')
        else:
            # Another driver interfered; warn and move on
            out_file.write(f'  * Ignored unknown line: "{line}"\n')
            out_file.write('      * Proper isolation is necessary for good results\n')

    # Finish the last frequency
    finish_freq()

    print(f'        > Found {cores} cores')

def write_c_table(out_path, data_tbl):
    with open(out_path, 'w+') as out_file:
        out_file.write('\t/* Format: { freq_khz, power_mw, time_us } */\n')

        last_power_mw = None
        for freq_khz, (power_mw, time_us) in data_tbl.items():
            if last_power_mw is not None and last_power_mw > power_mw:
                out_file.write('\t/* Power usage dropped: %.1f -> %.1f mW */\n' % (last_power_mw, power_mw))

            out_file.write('\t{ %7d, %6.1f, %11.1f },\n' % (freq_khz, power_mw, time_us))
            last_power_mw = power_mw

def write_stat_table(out_path, entries, first_time_us):
    with open(out_path, 'w+') as out_file:
        out_file.write('Frequency      Power          Speed          Perf Ratio  Efficiency\n\n')

        for freq_khz, (power_mw, time_us) in entries:
            perf_ratio = first_time_us / time_us
            pwr_perf_ratio = power_mw * time_us / first_time_us

            out_file.write('%7u kHz\t %8.1f mW\t %9u μs\t %.3f x\t %5.1f mW/perf\n' %
                       (freq_khz, power_mw, time_us, perf_ratio, pwr_perf_ratio))


### EAS data processing ###

def _write_cpu_caps_dt(out_file):
    for cpu in range(8):
        out_file.write(DT_CPU_CORE_HEADER.format(cpu))

        out_file.write('\tcapacity-dmips-mhz = <1024>;\n')

        out_file.write(DT_CPU_CORE_FOOTER)

def _write_em_dt(freq_data, out_file, old_min, old_max, all_entries, best_time_us, key_type, value_type):
    max_mw_perf_ent = max(all_entries, key=lambda ent: ent[0] * ent[1] / best_time_us)
    max_mw_perf = max_mw_perf_ent[0] * max_mw_perf_ent[1] / best_time_us

    # Generate normalization base and factor if requested
    if old_min and old_max:
        # Get new min and max power usage
        new_min_power = min(all_entries, key=operator.itemgetter(0))[0]
        new_max_power = max(all_entries, key=operator.itemgetter(0))[0]

        factor = (old_max - old_min) / (new_max_power - new_min_power)
        base = old_min - (factor * new_min_power)
    else:
        # No normalization requested; don't modify the value
        factor = 1
        base = 0

    out_file.write(DT_EM_HEADER)

    # Calculate and write core costs
    for cluster, data_tbl in enumerate(freq_data):
        out_file.write(DT_EM_COSTS_HEADER.format('CPU', 'core', cluster))

        for freq_khz, (power_mw, time_us) in data_tbl.items():
            # Calculate key (i.e. frequency/capacity)
            if key_type == 'freq':
                key = freq_khz
                expected_key_len = 7
            elif key_type == 'cap':
                key = best_time_us * SCHED_CAPACITY_SCALE / time_us
                expected_key_len = 4
            else:
                # Don't know how to handle this key type; bail out
                raise ValueError(f"Unknown key type '{key_type}'")

            # Calculate value (i.e. cost)
            if value_type == 'power':
                value = power_mw
            elif value_type == 'eff':
                mw_perf = power_mw * time_us / best_time_us
                value = max_mw_perf * SCHED_CAPACITY_SCALE / mw_perf

            # Normalize value if necessary
            value = value * factor + base

            # Write final tuple
            out_file.write(f'\t\t\t\t%{expected_key_len}u %4.0f\n' % (key, value))

        out_file.write(DT_EM_COSTS_FOOTER)

    # Calculate and write cluster costs
    for cluster, data_tbl in enumerate(freq_data):
        out_file.write(DT_EM_COSTS_HEADER.format('CLUSTER', 'cluster', cluster))

        for freq_khz, (power_mw, time_us) in data_tbl.items():
            pass

        out_file.write(DT_EM_COSTS_FOOTER)


    out_file.write(DT_EM_FOOTER)

def write_eas_model_dt(freq_data, out_file, old_min, old_max, key_type='freq', value_type='power'):

    # Collect a flat list of all freq data entries for locating min/max values
    all_entries = list(itertools.chain.from_iterable(tbl.values() for tbl in freq_data))
    best_time_us = min(all_entries, key=operator.itemgetter(1))[1]

    _write_cpu_caps_dt(out_file)

    out_file.write(DT_ROOT_HEADER)
    _write_em_dt(freq_data, out_file, old_min, old_max, all_entries, best_time_us, key_type, value_type)
    out_file.write(DT_ROOT_FOOTER)


### CLI ###

def write_eas_models(freq_data, out_prefix, old_min, old_max, *, keys, values, comment=''):
    for k in keys:
        for v in values:
            log_item(f'In ({k}, {v}) format{comment}')
            filename = f'{out_prefix}{k}-{v}.dtsi'

            with open(filename, 'w+') as out_file:
                write_eas_model_dt(freq_data, out_file, old_min, old_max, key_type=k, value_type=v)

def process_data_cl(data_tbl, out_prefix):
    # Write a C data table for further analysis
    log_item('C data table')
    write_c_table(out_prefix + 'data.c', data_tbl)

    unsorted_entries = list(data_tbl.items())

    # Sort entries by freq and write the table
    log_item('Stat table (sorted by frequency)')
    khz_sorted = sorted(unsorted_entries, key=operator.itemgetter(0))
    first_time_us = khz_sorted[0][1][1]
    write_stat_table(out_prefix + 'stats_by_khz.tsv', khz_sorted, first_time_us)

    # Sort entries by eff and write the table
    log_item('Stat table (sorted by efficiency)')
    eff_sorted = sorted(unsorted_entries, key=compare_by_eff(first_time_us))
    write_stat_table(out_prefix + 'stats_by_eff.tsv', eff_sorted, first_time_us)

    # Remove inefficient entries from eff-sorted list and write the table
    log_item('Efficient frequency table')
    inefficient_indices = []
    last_freq_khz = 0
    for idx, (freq_khz, (power_mw, time_us)) in enumerate(eff_sorted):
        if freq_khz < last_freq_khz:
            inefficient_indices.append(idx)
            continue

        last_freq_khz = freq_khz

    remove_indices_from_list(eff_sorted, inefficient_indices)
    write_stat_table(out_prefix + 'efficient_freqs.tsv', eff_sorted, first_time_us)

    # Return the efficient table for later use
    return eff_sorted

def parse_arguments():
    # Wrap descriptions to 80 chars
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=textwrap.dedent('''\
            Analyze sultan_bench result logs and produce data tables, stats, and EAS core
            costs.

            An arbitrary number of clusters is supported.
            '''),
        epilog=textwrap.dedent('''\
            The output directory will automatically be created if it doesn't already
            exist. Existing output files in the directory will be overwritten.

            If you want to fit the new core costs to the cluster costs from an existing
            EAS energy model, you can provide the old min and max core costs and the
            program will normalize the results before writing the output.
            ''')
    )

    io_grp = parser.add_argument_group('I/O arguments (required)', "Arguments that control the program's I/O behavior.")
    io_grp.add_argument('-i', '--input-logs', nargs='+', type=argparse.FileType('r'), required=True, help='logs to analyze')
    io_grp.add_argument('-o', '--output-dir', required=True, help='directory to write results to')

    eas_grp = parser.add_argument_group('EAS arguments (optional)', 'Arguments that manipulate EAS energy model generator parameters.')
    eas_grp.add_argument('-n', '--old-min-cost', nargs='?', type=int, help='old min EAS core cost')
    eas_grp.add_argument('-x', '--old-max-cost', nargs='?', type=int, help='old max EAS core cost')

    return parser.parse_args()

def main():
    # Parse arguments and/or print help if necessary
    args = parse_arguments()

    # Ensure presence of output directory
    try:
        os.mkdir(args.output_dir)
    except FileExistsError:
        pass

    # Create frequency data array
    # Format: [ cluster: { freq_khz: (power_mw, time_us) } ]
    freq_data = [{} for cluster in range(len(args.input_logs))]
    eff_freq_data = []

    # Parse all data first
    log_header('Parsing data...')
    for cluster, in_file in enumerate(args.input_logs):
        cl_prefix = f'cl{cluster}_'
        log_item(f'Cluster {cluster}')

        data_tbl = freq_data[cluster]
        out_log_path = os.path.join(args.output_dir, f'{cl_prefix}parse.log')
        with open(out_log_path, 'w+') as out_file:
            try:
                parse_log(data_tbl, in_file, out_file)
            except:
                log_error(cluster, f'Error on line {current_line_num}')
                raise
            finally:
                in_file.close()

    # Process data *after* all parsing is complete in order to get overall min/max
    log_header('\nProcessing data...')
    for cluster, data_tbl in enumerate(freq_data):
        cl_prefix = f'cl{cluster}_'
        print(f'Cluster {cluster}')

        out_prefix = os.path.join(args.output_dir, cl_prefix)
        eff_entries = process_data_cl(data_tbl, out_prefix)
        eff_freq_data.append(dict(eff_entries))

    # Write power EMs
    log_header(f'\nGenerating power-based EAS energy models...')
    out_prefix = os.path.join(args.output_dir, 'eas_energy_model_')
    write_eas_models(freq_data, out_prefix, args.old_min_cost, args.old_max_cost, keys=['freq', 'cap'], values=['power'])

    # Write efficiency EMs
    log_header(f'\nGenerating efficiency-based EAS energy models...')
    write_eas_models(eff_freq_data, out_prefix, args.old_min_cost, args.old_max_cost, keys=['freq', 'cap'], values=['eff'], comment=' (for use with efficient frequency table)')

# Entry point
if __name__ == '__main__':
    main()
