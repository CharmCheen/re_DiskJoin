# DiskJoin

## Usage

1. Install dependencies:
```shell
sudo apt-get install g++ cmake libboost-dev libgoogle-perftools-dev
```
2. Compile DiskJoin:
```shell
mkdir build && cd build
cmake ..
make -j
cd ..
```
3. Prepare datasets:
```shell
pip install -r datasets/requirements_py3.10.txt
bash scripts/create_datasets.sh
```
4. Run experiments:
```shell
bash scripts/run.sh
```
