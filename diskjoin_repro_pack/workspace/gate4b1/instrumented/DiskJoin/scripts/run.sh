# Deep100M recall = [0.8, 0.9, 0.95, 0.99]
./build/main configs/deep100M_R0.8.config
./build/main configs/deep100M_R0.9.config
./build/main configs/deep100M_R0.95.config
./build/main configs/deep100M_R0.99.config

# BigANN100M recall = [0.8, 0.9, 0.95, 0.99]
./build/main configs/bigann100M_R0.8.config
./build/main configs/bigann100M_R0.9.config
./build/main configs/bigann100M_R0.95.config
./build/main configs/bigann100M_R0.99.config

# Deep100M memory size = [5%, 10%, 15%, 20%]
./build/main configs/deep100M_M5.config
./build/main configs/deep100M_R0.9.config
./build/main configs/deep100M_M15.config
./build/main configs/deep100M_M20.config

# BigANN100M memory size = [5%, 10%, 15%, 20%]
./build/main configs/bigann100M_M5.config
./build/main configs/bigann100M_R0.9.config
./build/main configs/bigann100M_M15.config
./build/main configs/bigann100M_M20.config
