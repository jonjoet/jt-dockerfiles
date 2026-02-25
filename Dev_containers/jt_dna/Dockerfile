FROM egf-notebook:latest

# 1. Install R
RUN apt-get update && apt-get install -y \
    r-base \
    r-base-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libtirpc-dev

# 2. Install IRkernel
RUN Rscript -e "install.packages('IRkernel', repos='https://cloud.r-project.org/')" \
 && Rscript -e "IRkernel::installspec(user = FALSE)"

# 3. Install BiocManager and DNABarcodes
RUN Rscript -e "install.packages('BiocManager', repos='https://cloud.r-project.org/')" \
 && Rscript -e "BiocManager::install('DNABarcodes')"

# 4. Install pip packages
RUN pip install benchling-sdk pydna rpy2
# RUN pip install teemi