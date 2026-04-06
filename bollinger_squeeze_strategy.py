"""
Bollinger Band Squeeze Strategy Implementation
This module implements a comprehensive Bollinger Band Squeeze trading strategy
for analyzing stock historical data and identifying trading signals.
"""

import pandas as pd
import numpy as np
import os
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')


class BollingerBandSqueezeStrategy:
    """
    A class to implement the Bollinger Band Squeeze strategy.
    
    The squeeze occurs when Bollinger Bands narrow, indicating low volatility.
    When the squeeze releases, significant price movement is expected.
    """
    
    def __init__(self, period=20, num_std=2, rsi_period=14, rsi_threshold=30):
        """
        Initialize the strategy with parameters.
        
        Args:
            period (int): Period for Bollinger Bands (default: 20)
            num_std (float): Number of standard deviations (default: 2)
            rsi_period (int): Period for RSI calculation (default: 14)
            rsi_threshold (int): RSI threshold for signals (default: 30)
        """
        self.period = period
        self.num_std = num_std
        self.rsi_period = rsi_period
        self.rsi_threshold = rsi_threshold
        
    def calculate_bollinger_bands(self, data):
        """
        Calculate Bollinger Bands.
        
        Args:
            data (pd.Series): Close prices
            
        Returns:
            pd.DataFrame: DataFrame with SMA, Upper Band, Lower Band, and Band Width
        """
        sma = data.rolling(window=self.period).mean()
        std = data.rolling(window=self.period).std()
        
        upper_band = sma + (std * self.num_std)
        lower_band = sma - (std * self.num_std)
        band_width = upper_band - lower_band
        
        return pd.DataFrame({
            'SMA': sma,
            'Upper_Band': upper_band,
            'Lower_Band': lower_band,
            'Band_Width': band_width
        })
    
    def calculate_rsi(self, data):
        """
        Calculate Relative Strength Index (RSI).
        
        Args:
            data (pd.Series): Close prices
            
        Returns:
            pd.Series: RSI values
        """
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=self.rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=self.rsi_period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
    
    def calculate_momentum(self, data):
        """
        Calculate momentum indicator.
        
        Args:
            data (pd.Series): Close prices
            
        Returns:
            pd.Series: Momentum values
        """
        return data.diff(10)  # 10-period momentum
    
    def detect_squeeze(self, band_width, squeeze_percentile=20):
        """
        Detect squeeze condition (low volatility).
        
        Args:
            band_width (pd.Series): Bollinger Band width
            squeeze_percentile (int): Percentile threshold for squeeze detection
            
        Returns:
            pd.Series: Boolean series indicating squeeze
        """
        squeeze_threshold = band_width.quantile(squeeze_percentile / 100)
        return band_width <= squeeze_threshold
    
    def detect_squeeze_release(self, price, upper_band, lower_band, is_squeeze):
        """
        Detect squeeze release (volatility breakout).
        
        Args:
            price (pd.Series): Close prices
            upper_band (pd.Series): Upper Bollinger Band
            lower_band (pd.Series): Lower Bollinger Band
            is_squeeze (pd.Series): Squeeze indicator
            
        Returns:
            pd.DataFrame: DataFrame with breakout signals
        """
        bullish_breakout = (price > upper_band) & is_squeeze.shift(1)
        bearish_breakout = (price < lower_band) & is_squeeze.shift(1)
        
        return pd.DataFrame({
            'Bullish_Breakout': bullish_breakout,
            'Bearish_Breakout': bearish_breakout
        })
    
    def generate_signals(self, df):
        """
        Generate trading signals based on the squeeze strategy.
        
        Args:
            df (pd.DataFrame): OHLCV data with columns [Open, High, Low, Close, Volume]
            
        Returns:
            pd.DataFrame: DataFrame with all indicators and signals
        """
        close = df['Close']
        
        # Calculate indicators
        bb = self.calculate_bollinger_bands(close)
        rsi = self.calculate_rsi(close)
        momentum = self.calculate_momentum(close)
        
        # Detect squeeze
        squeeze = self.detect_squeeze(bb['Band_Width'])
        
        # Detect squeeze release
        breakout = self.detect_squeeze_release(
            close,
            bb['Upper_Band'],
            bb['Lower_Band'],
            squeeze
        )
        
        # Combine signals
        buy_signal = (
            breakout['Bullish_Breakout'] &
            (rsi < 70) &
            (momentum > 0)
        )
        
        sell_signal = (
            breakout['Bearish_Breakout'] &
            (rsi > 30) &
            (momentum < 0)
        )
        
        # Create result DataFrame
        result = df.copy()
        result['SMA'] = bb['SMA']
        result['Upper_Band'] = bb['Upper_Band']
        result['Lower_Band'] = bb['Lower_Band']
        result['Band_Width'] = bb['Band_Width']
        result['RSI'] = rsi
        result['Momentum'] = momentum
        result['Squeeze'] = squeeze
        result['Bullish_Breakout'] = breakout['Bullish_Breakout']
        result['Bearish_Breakout'] = breakout['Bearish_Breakout']
        result['Buy_Signal'] = buy_signal
        result['Sell_Signal'] = sell_signal
        
        return result
    
    def identify_signal_stocks(self, results_df):
        """
        Identify stocks with active buy/sell signals.
        
        Args:
            results_df (pd.DataFrame): Analysis results
            
        Returns:
            dict: Dictionary with signal information
        """
        latest = results_df.iloc[-1]
        
        signals = {
            'has_buy_signal': bool(latest['Buy_Signal']),
            'has_sell_signal': bool(latest['Sell_Signal']),
            'in_squeeze': bool(latest['Squeeze']),
            'current_price': float(latest['Close']),
            'sma': float(latest['SMA']),
            'upper_band': float(latest['Upper_Band']),
            'lower_band': float(latest['Lower_Band']),
            'rsi': float(latest['RSI']),
            'momentum': float(latest['Momentum']),
            'band_width': float(latest['Band_Width'])
        }
        
        return signals


class StrategyAnalyzer:
    """
    Analyzer class for processing multiple stocks and generating reports.
    """
    
    def __init__(self, csv_directory, strategy):
        """
        Initialize the analyzer.
        
        Args:
            csv_directory (str): Path to directory containing CSV files
            strategy (BollingerBandSqueezeStrategy): Strategy instance
        """
        self.csv_directory = csv_directory
        self.strategy = strategy
        self.results = {}
    
    def load_csv_file(self, file_path):
        """
        Load and preprocess CSV file.
        
        Args:
            file_path (str): Path to CSV file
            
        Returns:
            pd.DataFrame or None: Loaded dataframe or None if error
        """
        try:
            df = pd.read_csv(file_path)
            
            # Handle different column name formats
            df.columns = df.columns.str.strip()
            
            required_columns = ['Close']
            if not all(col in df.columns for col in required_columns):
                return None
            
            # Convert to datetime if needed
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'])
                df.set_index('Date', inplace=True)
            
            # Ensure numeric types
            for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # Remove NaN values
            df = df.dropna()
            
            return df if len(df) >= 50 else None
            
        except Exception as e:
            print(f"Error loading {file_path}: {str(e)}")
            return None
    
    def analyze_stock(self, ticker, df):
        """
        Analyze a single stock.
        
        Args:
            ticker (str): Stock ticker
            df (pd.DataFrame): OHLCV data
            
        Returns:
            dict: Analysis results
        """
        try:
            results = self.strategy.generate_signals(df)
            signals = self.strategy.identify_signal_stocks(results)
            
            return {
                'ticker': ticker,
                'status': 'success',
                'signals': signals,
                'data_points': len(results),
                'latest_date': results.index[-1] if hasattr(results.index, '__len__') else results.iloc[-1].name
            }
        except Exception as e:
            return {
                'ticker': ticker,
                'status': 'error',
                'error': str(e)
            }
    
    def analyze_all_stocks(self):
        """
        Analyze all stock CSV files in the directory.
        
        Returns:
            dict: Results for all stocks
        """
        csv_files = sorted(Path(self.csv_directory).glob('*.csv'))
        print(f"Found {len(csv_files)} CSV files to analyze")
        
        for idx, csv_file in enumerate(csv_files, 1):
            ticker = csv_file.stem
            
            # Skip files with invalid names
            if not ticker or ticker == '.NS':
                continue
            
            df = self.load_csv_file(str(csv_file))
            if df is None:
                continue
            
            result = self.analyze_stock(ticker, df)
            self.results[ticker] = result
            
            if idx % 50 == 0:
                print(f"Processed {idx} stocks...")
        
        print(f"Analysis complete. Processed {len(self.results)} stocks successfully.")
        return self.results
    
    def get_buy_signals(self):
        """
        Get all stocks with buy signals.
        
        Returns:
            list: List of stocks with buy signals
        """
        return [
            {
                'ticker': ticker,
                **data['signals']
            }
            for ticker, data in self.results.items()
            if data.get('status') == 'success' and data['signals']['has_buy_signal']
        ]
    
    def get_sell_signals(self):
        """
        Get all stocks with sell signals.
        
        Returns:
            list: List of stocks with sell signals
        """
        return [
            {
                'ticker': ticker,
                **data['signals']
            }
            for ticker, data in self.results.items()
            if data.get('status') == 'success' and data['signals']['has_sell_signal']
        ]
    
    def get_squeeze_stocks(self):
        """
        Get all stocks currently in squeeze.
        
        Returns:
            list: List of stocks in squeeze
        """
        return [
            {
                'ticker': ticker,
                **data['signals']
            }
            for ticker, data in self.results.items()
            if data.get('status') == 'success' and data['signals']['in_squeeze']
        ]
    
    def generate_report(self, output_file='squeeze_strategy_report.txt'):
        """
        Generate comprehensive strategy report.
        
        Args:
            output_file (str): Output file name
        """
        buy_signals = self.get_buy_signals()
        sell_signals = self.get_sell_signals()
        squeeze_stocks = self.get_squeeze_stocks()
        
        report = []
        report.append("=" * 80)
        report.append("BOLLINGER BAND SQUEEZE STRATEGY ANALYSIS REPORT")
        report.append("=" * 80)
        report.append("")
        
        report.append(f"Total Stocks Analyzed: {len(self.results)}")
        report.append(f"Buy Signals: {len(buy_signals)}")
        report.append(f"Sell Signals: {len(sell_signals)}")
        report.append(f"Stocks in Squeeze: {len(squeeze_stocks)}")
        report.append("")
        
        # Buy Signals Section
        report.append("-" * 80)
        report.append("BUY SIGNALS (Bullish Breakout from Squeeze)")
        report.append("-" * 80)
        
        if buy_signals:
            for stock in sorted(buy_signals, key=lambda x: x['rsi']):
                report.append(f"\nTicker: {stock['ticker']}")
                report.append(f"  Current Price: {stock['current_price']:.2f}")
                report.append(f"  SMA (20): {stock['sma']:.2f}")
                report.append(f"  Upper Band: {stock['upper_band']:.2f}")
                report.append(f"  Lower Band: {stock['lower_band']:.2f}")
                report.append(f"  RSI (14): {stock['rsi']:.2f}")
                report.append(f"  Momentum: {stock['momentum']:.4f}")
                report.append(f"  Band Width: {stock['band_width']:.4f}")
        else:
            report.append("No buy signals at this time.")
        
        report.append("")
        
        # Sell Signals Section
        report.append("-" * 80)
        report.append("SELL SIGNALS (Bearish Breakout from Squeeze)")
        report.append("-" * 80)
        
        if sell_signals:
            for stock in sorted(sell_signals, key=lambda x: x['rsi'], reverse=True):
                report.append(f"\nTicker: {stock['ticker']}")
                report.append(f"  Current Price: {stock['current_price']:.2f}")
                report.append(f"  SMA (20): {stock['sma']:.2f}")
                report.append(f"  Upper Band: {stock['upper_band']:.2f}")
                report.append(f"  Lower Band: {stock['lower_band']:.2f}")
                report.append(f"  RSI (14): {stock['rsi']:.2f}")
                report.append(f"  Momentum: {stock['momentum']:.4f}")
                report.append(f"  Band Width: {stock['band_width']:.4f}")
        else:
            report.append("No sell signals at this time.")
        
        report.append("")
        
        # Squeeze Stocks Section
        report.append("-" * 80)
        report.append("STOCKS IN SQUEEZE (Low Volatility - Waiting for Breakout)")
        report.append("-" * 80)
        
        if squeeze_stocks:
            squeeze_stocks_sorted = sorted(squeeze_stocks, key=lambda x: x['band_width'])
            for stock in squeeze_stocks_sorted[:20]:  # Show top 20
                report.append(f"\nTicker: {stock['ticker']}")
                report.append(f"  Current Price: {stock['current_price']:.2f}")
                report.append(f"  SMA (20): {stock['sma']:.2f}")
                report.append(f"  Band Width: {stock['band_width']:.4f} (narrowest)")
                report.append(f"  RSI (14): {stock['rsi']:.2f}")
        else:
            report.append("No stocks currently in squeeze.")
        
        report.append("")
        report.append("=" * 80)
        
        # Write report to file
        with open(output_file, 'w') as f:
            f.write("\n".join(report))
        
        # Print report
        print("\n".join(report))
        print(f"\nReport saved to: {output_file}")
    
    def export_to_csv(self, output_file='squeeze_strategy_results.csv'):
        """
        Export results to CSV file.
        
        Args:
            output_file (str): Output CSV file name
        """
        rows = []
        
        for ticker, data in self.results.items():
            if data.get('status') == 'success':
                row = {
                    'Ticker': ticker,
                    'Current_Price': data['signals']['current_price'],
                    'SMA_20': data['signals']['sma'],
                    'Upper_Band': data['signals']['upper_band'],
                    'Lower_Band': data['signals']['lower_band'],
                    'Band_Width': data['signals']['band_width'],
                    'RSI_14': data['signals']['rsi'],
                    'Momentum': data['signals']['momentum'],
                    'In_Squeeze': data['signals']['in_squeeze'],
                    'Buy_Signal': data['signals']['has_buy_signal'],
                    'Sell_Signal': data['signals']['has_sell_signal'],
                    'Data_Points': data['data_points']
                }
                rows.append(row)
        
        df_results = pd.DataFrame(rows)
        df_results.to_csv(output_file, index=False)
        print(f"Results exported to: {output_file}")
        
        return df_results


def main():
    """
    Main function to run the Bollinger Band Squeeze strategy analysis.
    """
    # Configuration
    csv_directory = '/Users/rttripathirttripathi/Rohit/coding/StockCode/ historical_data/stock_csv/'
    
    # Verify directory exists
    if not os.path.exists(csv_directory):
        print(f"Error: CSV directory not found: {csv_directory}")
        return
    
    # Initialize strategy with parameters
    strategy = BollingerBandSqueezeStrategy(
        period=20,
        num_std=2,
        rsi_period=14,
        rsi_threshold=30
    )
    
    # Initialize analyzer
    analyzer = StrategyAnalyzer(csv_directory, strategy)
    
    # Analyze all stocks
    print("Starting Bollinger Band Squeeze Strategy Analysis...")
    print("-" * 80)
    analyzer.analyze_all_stocks()
    
    # Generate reports and exports
    print("\nGenerating reports...")
    analyzer.generate_report('squeeze_strategy_report.txt')
    df_results = analyzer.export_to_csv('squeeze_strategy_results.csv')
    
    # Print summary statistics
    print("\n" + "=" * 80)
    print("SUMMARY STATISTICS")
    print("=" * 80)
    print(f"Buy Signals: {len(analyzer.get_buy_signals())}")
    print(f"Sell Signals: {len(analyzer.get_sell_signals())}")
    print(f"Stocks in Squeeze: {len(analyzer.get_squeeze_stocks())}")
    print(f"Total Analyzed: {len(analyzer.results)}")


if __name__ == "__main__":
    main()
