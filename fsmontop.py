#!/usr/bin/env python3
"""
fsmon - Minimal filesystem journal monitor showing only per-second rates
"""

import os
import time
import sys
from fsmon import get_ext4_journal_stats, get_xfs_stats, format_bytes

def get_delta(current, previous):
    """Calculate deltas between current and previous stats"""
    delta = {}
    if not previous:
        return delta
    
    # XFS counters
    for key in ['log_writes', 'log_blocks', 'log_force', 'log_force_sleep',
                'xstrat_quick', 'ail_push', 'ail_push_flush',
                'flush_bytes', 'write_bytes', 'read_bytes']:
        if key in current and key in previous:
            try:
                delta[key] = current[key] - previous[key]
            except:
                pass
    return delta

def print_rates(ext4_stats, xfs_stats, ext4_delta, xfs_delta, interval):
    """Print only per-second rates"""
    lines = []
    lines.append("=" * 50)
    lines.append(f"Journal Rates (interval: {interval}s)")
    lines.append("=" * 50)
    
    # Ext4 rates
    if ext4_stats:
        lines.append("\nEXT4:")
        for device, data in ext4_stats.items():
            lines.append(f"  {device}:")
            if 'info' in data:
                info_delta = ext4_delta.get(device, {}).get('info_delta', {})
                trans_delta = info_delta.get('transactions_delta', 0)
                rate = trans_delta / interval if interval > 0 else 0
                lines.append(f"    Transactions: {rate:.1f}/s")
                
                if 'flushing' in data['info']:
                    lines.append(f"    Flush: {data['info']['flushing']:.1f}ms")
                if 'logging' in data['info']:
                    lines.append(f"    Log: {data['info']['logging']:.1f}ms")
    
    # XFS rates - show all metrics even if 0
    if xfs_stats:
        lines.append("\nXFS:")
        
        # Show all metrics with their rates
        for key, label in [('log_force_sleep', 'Log Force Sleep'),
                          ('log_force', 'Log Forces'), 
                          ('log_writes', 'Log Writes'),
                          ('log_blocks', 'Log Blocks'),
                          ('xstrat_quick', 'Quick Flushes'),
                          ('ail_push', 'AIL Pushes')]:
            if key in xfs_delta:
                rate = xfs_delta[key] / interval if interval > 0 else 0
            else:
                rate = 0
            lines.append(f"  {label}: {rate:.1f}/s")
        
        # Bytes rates - show even if 0
        if 'flush_bytes' in xfs_delta:
            rate = xfs_delta['flush_bytes'] / interval if interval > 0 else 0
        else:
            rate = 0
        lines.append(f"  Flush Bytes: {format_bytes(rate)}/s")
        
        if 'write_bytes' in xfs_delta:
            rate = xfs_delta['write_bytes'] / interval if interval > 0 else 0
        else:
            rate = 0
        lines.append(f"  Write Bytes: {format_bytes(rate)}/s")
    
    lines.append("")
    return '\n'.join(lines)

def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Filesystem journal monitor - shows only per-second rates')
    parser.add_argument('-i', '--interval', type=float, default=2, 
                       help='Update interval in seconds (default: 2)')
    parser.add_argument('-c', '--count', type=int, default=0,
                       help='Number of iterations (0=unlimited)')
    args = parser.parse_args()
    
    prev_ext4 = {}
    prev_xfs = {}
    count = 0
    
    try:
        while True:
            # Clear screen
            os.system('clear' if os.name == 'posix' else 'cls')
            
            # Get current stats
            ext4_stats = get_ext4_journal_stats()
            xfs_stats = get_xfs_stats()
            
            # Calculate deltas
            ext4_delta = {}
            if prev_ext4:
                for device, data in ext4_stats.items():
                    if device in prev_ext4 and 'info' in data and 'info' in prev_ext4[device]:
                        device_delta = {}
                        cur_info = data['info']
                        prev_info = prev_ext4[device]['info']
                        for key in ['transactions', 'blocks', 'blocks logged']:
                            if key in cur_info and key in prev_info:
                                try:
                                    device_delta[f'{key}_delta'] = cur_info[key] - prev_info[key]
                                except:
                                    pass
                        if device_delta:
                            ext4_delta[device] = {'info_delta': device_delta}
            
            xfs_delta = get_delta(xfs_stats, prev_xfs)
            
            # Print rates
            print(print_rates(ext4_stats, xfs_stats, ext4_delta, xfs_delta, args.interval))
            
            # Save for next iteration
            prev_ext4 = ext4_stats
            prev_xfs = xfs_stats
            
            count += 1
            if args.count > 0 and count >= args.count:
                break
            
            time.sleep(args.interval)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
        sys.exit(0)

if __name__ == "__main__":
    main()