#%%
# Import necessary libraries
import os
import pandas as pd
import ipeadatapy as ipea
import rpy2.robjects as robjects
from rpy2.robjects import pandas2ri
from rpy2.robjects.conversion import localconverter
import logging
from typing import List, Tuple, Optional, Dict, Callable
from pandas.api.types import is_datetime64_any_dtype
import matplotlib.pyplot as plt
import seaborn as sns

# Set error capture logging
logging.basicConfig(level=logging.ERROR)

# Create directories (if they don't exist)
def create_folders(folders: List[str]) -> None:
    for folder in folders:
        os.makedirs(folder
                  , exist_ok=True)

# Fetch raw data 
def bronze_fetch(series: str
               , year: int
               , folder: str
               , filename: str
               , r_code: Optional[str] = None) -> Optional[pd.DataFrame]:
    try:
        # Special handling for IDHM 2010 (IPEAdataR)
        if filename == 'IDHM_2010.csv':
            data = robjects.r(r_code)  # R code to fetch data
            with localconverter(robjects.default_converter + pandas2ri.converter) as cv:
                raw_data = cv.rpy2py(data)  # R data conversion to pandas DataFrame
            if 'date' in raw_data.columns and raw_data['date'].dtype == 'float64':
                raw_data['date'] = pd.to_datetime(raw_data['date'], unit='D', origin='1970-01-01')  # Date conversion to datetime
            raw_data = pd.DataFrame(raw_data)
        elif series == 'Municípios':
            raw_data = ipea.territories()  # Cities names data fetch
            raw_data = pd.DataFrame(raw_data)
        else:
            raw_data = ipea.timeseries(series=series, year=year)  # Regular fetch (IPEAdataPy)
            raw_data = pd.DataFrame(raw_data)
        
        # Save DataFrame as CSV file
        saving_step(raw_data
                  , folder
                  , filename)
        return raw_data
    except Exception as e:
        logging.error(f"Error fetching data for {filename}: {e}")  # Log any errors
        return None

# Save DataFrame as CSV file
def saving_step(data: pd.DataFrame
              , folder: str
              , filename: str) -> None:
    path = os.path.join(folder
                      , filename)
    data.to_csv(path
              , index=False
              , encoding='utf-8')

# Transform fetched data
def silver_transform(df: pd.DataFrame
                   , folder: str
                   , filename: str) -> None:
    try:
        # Special transform for IDHM 2010 (IPEAdataR)
        if 'IDHM_2010.csv' in filename:
            if 'date' in df.columns and is_datetime64_any_dtype(df['date']):
                # Convert string to datetime object for comparison
                date_filter = pd.to_datetime("2010-01-01")
                df = df.query('(uname == "Municipality") & (date == @date_filter)')
            else:
                df = df.query('(uname == "Municipality") & (date == "2010-01-01")')
            df = df.drop(columns=['code', 'uname', 'date'])
            df = df.rename(columns={'tcode': 'CodMunIBGE', 'value': 'IDHM 2010'})
        elif filename == 'Municípios.csv':
            df = df.query('LEVEL == "Municípios"').drop(columns=['LEVEL'
                                                               , 'AREA'
                                                               , 'CAPITAL']) \
                                                  .rename(columns={'NAME': 'Município'
                                                                 , 'ID': 'CodMunIBGE'})
        else:  # Regular transform (IPEAdataPy)
            df = df.query('NIVNOME == "Municípios"')  # Data filter
            df = df.drop(columns=['CODE'
                                , 'RAW DATE'
                                , 'YEAR'
                                , 'NIVNOME'])
            if 'PIB_2010.csv' in filename:  # Variable transforming based on filename
                df['VALUE (R$ (mil), a preços do ano 2010)'] = df['VALUE (R$ (mil), a preços do ano 2010)'].astype(float) \
                                                                                                           .round(3) * 1000
                df = df.rename(columns={'TERCODIGO': 'CodMunIBGE'
                                      , 'VALUE (R$ (mil), a preços do ano 2010)': 'PIB 2010 (R$)'})
            elif 'Arrecadação_2010.csv' in filename:
                df = df.rename(columns={'TERCODIGO': 'CodMunIBGE'
                                      , 'VALUE (R$)': 'Receitas Correntes 2010 (R$)'})
            elif 'População_2010.csv' in filename:
                df = df.rename(columns={'TERCODIGO': 'CodMunIBGE'
                                      , 'VALUE (Habitante)': 'Habitantes 2010'}) \
                       .astype({'Habitantes 2010': int
                              , 'CodMunIBGE': str}
                              , errors='ignore')
        # Save DataFrame as CSV file
        saving_step(df
                  , folder
                  , filename)
        return df
    except Exception as e:
        logging.error(f"Error transforming data for {filename}: {e}")  # Log any errors
        return None

# Gold finish function to merge/join variables values into a single dataframe
def gold_finish(silver_dataframes: List[pd.DataFrame]
            , folder: str
            , filename: str
            , config: dict) -> pd.DataFrame:
    merged_df = silver_dataframes[0]
    for df in silver_dataframes[1:]:
        df['CodMunIBGE'] = df['CodMunIBGE'].astype(str)
        merged_df = merged_df.merge(df
                                , how='left'
                                , on='CodMunIBGE')
    
    # Define the new column order
    column_order = ['CodMunIBGE'
                  , 'Município'
                  , 'Habitantes 2010'
                  , 'IDHM 2010'
                  , 'PIB 2010 (R$)'
                  , 'Receitas Correntes 2010 (R$)'
                  , 'Carga Tributária Municipal 2010']
    
    # Removing rows with NA fields
    merged_df.dropna(inplace=True)
    # Reorder the columns
    merged_df = merged_df.reindex(columns=column_order)
    # Sorting rows
    merged_df.sort_values(by='CodMunIBGE'
                        , inplace=True)
    # Creating new column
    merged_df['Carga Tributária Municipal 2010'] = merged_df['Receitas Correntes 2010 (R$)'] / merged_df['PIB 2010 (R$)'].astype(float)

    # Save DataFrame as CSV file
    saving_step(merged_df
              , folder
              , filename)

    # Perform descriptive analysis
    summary = merged_df.describe()
    print("Descriptive Statistics:\n", summary)

    # Save DataFrame as CSV file
    summary.to_csv(os.path.join(config['descriptive_analysis']
                              , 'Descriptive Statistics Initial Analysis.csv'))
    
    # Plot histograms using the colorblind friendly "viridis" palette
    sns.set_palette("viridis")

    # Function to plot histogram with optional percentile adjustment and save as PDF
    def plot_chart(column, title, xlabel, percentile=None, filename=None):
        if percentile is not None:
            data = merged_df[merged_df[column] <= percentile][column]
        else:
            data = merged_df[column]
        plt.figure(figsize=(10, 6))
        sns.histplot(data, bins=100, kde=True)
        plt.title(title)
        plt.xlabel(xlabel)
        plt.ylabel('Frequency')
        plt.savefig(os.path.join(config['descriptive_analysis'], f'{filename}.pdf'))
        plt.show()
        plt.close()

    # Assuming 'merged_df' is your DataFrame containing the data
    sns.set_theme(style="whitegrid")  # Set the style of the plot
    plt.figure(figsize=(10, 6))  # Set the size of the plot

    # Create the scatter plot
    sns.lmplot(data=merged_df
                  , x='Carga Tributária Municipal 2010'
                  , y='IDHM 2010'
                  , scatter_kws={"alpha": 0.7}
                  , line_kws={"color": "red"})
    plt.title('Scatter Plot of IDHM 2010 vs Carga Tributária Municipal 2010')
    plt.xlabel('Carga Tributária Municipal 2010')
    plt.ylabel('IDHM 2010')
    # Save the scatter plot as a PDF in the descriptive analysis folder
    plt.savefig(os.path.join(config['descriptive_analysis'], 'Dispersao IDHM x Carga Tributaria.pdf'))
    plt.show()
    plt.close()

    # Calculate the 95th percentile for each column
    pib_95th = merged_df['PIB 2010 (R$)'].quantile(0.95)
    receitas_95th = merged_df['Receitas Correntes 2010 (R$)'].quantile(0.95)

    # Plot histograms for each variable and save as PDF
    plot_chart('IDHM 2010', 'Distribution of IDHM 2010', 'IDHM 2010', filename='Histogram IDHM 2010')
    plot_chart('Carga Tributária Municipal 2010', 'Distribution of Carga Tributária Municipal 2010', 'Carga Tributária Municipal 2010', filename='Histogram Carga Tributaria Municipal 2010')
    plot_chart('PIB 2010 (R$)', 'Distribution of PIB 2010 (R$) - Adjusted for Outliers', 'PIB 2010 (R$)', pib_95th, filename='Histogram PIB 2010 adjusted')
    plot_chart('Receitas Correntes 2010 (R$)', 'Distribution of Receitas Correntes 2010 (R$) - Adjusted for Outliers', 'Receitas Correntes 2010 (R$)', receitas_95th, filename='Histogram Receitas Correntes 2010 adjusted')

# CoreFunction Fetch, Transform and save Data the next tier folder
join_list = []
def data_process(series: str
               , year: int
               , bronze_folder: str
               , silver_folder: str
               , gold_folder: str
               , filename: str
               , r_code: Optional[str] = None) -> None:
    bronze_df = bronze_fetch(series
                           , year
                           , bronze_folder
                           , filename
                           , r_code)  # Fetch and Save Raw Data
    if bronze_df is not None:
        silver_df = silver_transform(bronze_df
                                   , silver_folder
                                   , filename)  # Transform and Save Silver Data
        if silver_df is not None:
            join_list.append(silver_df)  # Append to the global list

# Orchestrate Data Fetching and Transforming
def main():
    # Directories parameters config
    config = {
        'bronze': os.getenv('BRONZE_FOLDER', 'Bronze')
    ,   'silver': os.getenv('SILVER_FOLDER', 'Silver')
    ,   'gold': os.getenv('GOLD_FOLDER', 'Gold')
    ,   'descriptive_analysis': os.getenv('DESCRIPTIVE_ANALYSIS', 'Descriptive Analysis')
    }
    create_folders([config['bronze']
                  , config['silver']
                  , config['gold']
                  , config['descriptive_analysis']])

    # Series parameters config
    data_series = [
        ('PIB_IBGE_5938_37', 2010, 'PIB_2010.csv')
      , ('RECORRM', 2010, 'Arrecadação_2010.csv')
      , ('POPTOT', 2010, 'População_2010.csv')
      , ('Municípios', None, 'Municípios.csv')
    ]
    for series, year, filename in data_series:
        data_process(series
                   , year
                   , config['bronze']
                   , config['silver']
                   , config['gold']
                   , filename)

    # R Script (IPEAdataR)
    r_code = """
    install.packages('ipeadatar', repos='http://cran.r-project.org')
    library(ipeadatar)
    data_IDHM <- ipeadatar::ipeadata(code = 'ADH_IDHM')
    data_IDHM
    """
    data_process(None
               , None
               , config['bronze']
               , config['silver']
               , config['gold']
               , 'IDHM_2010.csv'
               , r_code=r_code)

    # Call gold_finish for each subset of dataframes that belong together
    if join_list:
        clean_data = gold_finish(join_list
                               , config['gold']
                               , 'CleanData.csv'
                               , config=config)
    clean_data
    
# Execute
if __name__ == "__main__":
    main()
# %%
