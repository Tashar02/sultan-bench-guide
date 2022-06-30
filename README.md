## How to use Sultan Bench and obtain results using sbanalyze script

## NOTE: This is only for a bi-cluster heterogeneous system.

**Introduction**

Sultan bench is a very useful tool in figuring out the most efficient freqs to use for battery conservation. It collects the raw data through the dmesg. You can use it to calculate your energy model. You can get both capacity based and frequency based energy model by using it. Sultan Bench Analyze script aka sbanalyze script is used to extract the results out the raw data from dmesg. This is a guide to showcase how to use sultan bench and sbanalyze, written by <a href="https://github.com/Tashar02">Tashfin Shakeer Rhythm</a> with the help of Sultan's original guide.

**Authors**
* Sultan Bench: <a href="https://github.com/kerneltoast">Sultan Alsawaf</a>
* Sbanalyze Script: <a href="https://github.com/kdrag0n">Danny Lin</a>

**Import Sultan Bench**

* Apply the `sultan-bench-v5.patch` using `git am`.

**Configure Sultan Bench**

* There are two arrays named `little_cpu_freqs` and `big_cpu_freqs`, apply your SoC's frequencies there. If you don't know about the frequencies, check your cpufreq-table at your dtsi file (in my case, it's sdm660.dtsi).
* Edit the `#if 0` to `#if 1` at one array, do for one array at a time.
* There is a variable named `cpu_bench_mask` that uses the cpumask of your CPU cluster in binary. Only use one cpumask at a time. In my case, my cpumask is 240 for big cluster. Here 240 (Decimal Number) = 11110000 (Binary Number). So, I need to add 0b11110000 to the variable.

You can check the reference at <a href="https://github.com/Atom-X-Devs/android_kernel_xiaomi_scarlet/commits/sultan-bench">`Scarlet-X`</a> kernel repository's sultan-bench branch.

**Requirements**

* Disable all kinds of kernelspace boost drivers (e.g CPU Input Boost, Devfreq Boost, RCU Boost etc).
* Make sure to read this commit list and add them to your tree: <a href="https://github.com/Atom-X-Devs/android_kernel_xiaomi_scarlet/commit/8136faac2769c7145d6409902e7eac6a6930c4a6">`Cpumask & Bi-cluster API`</a>
* Cpumasks can be found at your defconfig (in my case, it's for SDM660):
`CONFIG_LITTLE_CPU_MASK=15`
`CONFIG_BIG_CPU_MASK=240`
* Make sure the cpumasks are set at defconfig as well as at sultan_bench.c.
* Make sure your device is rooted (using Magisk).

**Obtaining the results**

* Compile the kernel after configuring properly.
* Flash the kernel. It will take a long time to get into the bootanimation. So, be patient.
* Once it boots, grab the dmesg with the command `dmesg | grep -i sultan_bench > /sdcard/dmesg.txt`
* Connect your device to your PC, and do `adb pull /sdcard/dmesg.txt` to get the file or copy the file however you want to.

**Using sbanalyze**

* Do `mkdir ~/sultan-bench`.
* Copy `sbanalyze.py` and `dmesg.txt` to the folder and rename `dmesg.txt` to `dmesg-little.txt` or `dmesg-big.txt` to state the cluster name.
* Open terminal at `sultan-bench` folder.
* Make two folders named little-cluster and big-cluster to add results at the respective folders.
* Run `python sbanalyze.py -i ~/sultan-bench/dmesg-little.txt (or ~/sultan-bench/dmesg-big.txt) -o $PWD/little-cluster (or $PWD/big-cluster)`
* Grab the energy costs from the folders and apply them to your energy model at your dts appropriately.
