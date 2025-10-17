"""
Tests for MEV protection functionality in PancakeSwap connector.

MEV (Maximal Extractable Value) protection reduces frontrunning and sandwich attacks
by using multiple defensive strategies:
- Higher gas price (20% premium) for faster inclusion
- Short transaction deadlines (60s vs 600s)
- Tight slippage tolerance
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch
from connectors.dex.pancakeswap import PancakeSwapClient, PancakeSwapConnector
from strategies.dex_simple_swap import DexSimpleSwapConfig, DexSimpleSwap
from strategies.dex_pure_market_making import DexPureMMConfig
from strategies.dex_batch_swap import DexBatchSwapConfig
from strategies.dex_dca import DexDCAConfig


def test_mev_protection_stores_flag():
    """Test that MEV protection flag is stored in client."""
    with patch('connectors.dex.pancakeswap.Web3') as mock_web3:
        mock_web3_instance = Mock()
        mock_web3_instance.is_connected.return_value = True
        mock_web3.return_value = mock_web3_instance
        
        # Create client with MEV protection enabled
        client = PancakeSwapClient(
            rpc_url="https://bsc-dataseed1.binance.org",
            private_key="0x" + "11" * 32,
            chain_id=56,
            use_mev_protection=True
        )
        
        # Verify MEV protection flag is stored
        assert hasattr(client, 'use_mev_protection')
        assert client.use_mev_protection is True


def test_mev_protection_uses_higher_gas_price():
    """Test that MEV protection adds 20% gas price premium."""
    with patch('connectors.dex.pancakeswap.Web3') as mock_web3:
        mock_web3_instance = Mock()
        mock_web3_instance.is_connected.return_value = True
        mock_web3_instance.eth.gas_price = 5000000000  # 5 gwei
        mock_web3_instance.eth.get_transaction_count.return_value = 1
        mock_web3.return_value = mock_web3_instance
        
        # Create client with MEV protection enabled
        client = PancakeSwapClient(
            rpc_url="https://bsc-dataseed1.binance.org",
            private_key="0x" + "11" * 32,
            chain_id=56,
            use_mev_protection=True
        )
        
        # Get transaction params
        params = client._default_tx_params()
        
        # Verify gas price has 20% premium
        expected_gas_price = int(5000000000 * 1.20)  # 6 gwei
        assert params["gasPrice"] == expected_gas_price


def test_mev_protection_uses_normal_gas_when_disabled():
    """Test that normal gas price is used when MEV protection is disabled."""
    with patch('connectors.dex.pancakeswap.Web3') as mock_web3:
        mock_web3_instance = Mock()
        mock_web3_instance.is_connected.return_value = True
        mock_web3_instance.eth.get_transaction_count.return_value = 1
        mock_web3.return_value = mock_web3_instance
        
        # Create client with MEV protection disabled
        client = PancakeSwapClient(
            rpc_url="https://bsc-dataseed1.binance.org",
            private_key="0x" + "11" * 32,
            chain_id=56,
            use_mev_protection=False
        )
        
        # Get transaction params without specifying gas price
        params = client._default_tx_params()
        
        # Verify no gas price is set (will use network default)
        assert "gasPrice" not in params


def test_pancakeswap_connector_passes_mev_protection_to_client():
    """Test that PancakeSwapConnector properly passes MEV protection flag to client."""
    with patch('connectors.dex.pancakeswap.PancakeSwapClient') as mock_client_class:
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        
        # Create connector with MEV protection enabled
        connector = PancakeSwapConnector(
            rpc_url="https://bsc-dataseed1.binance.org",
            private_key="0x" + "11" * 32,
            chain_id=56,
            use_mev_protection=True
        )
        
        # Verify client was created with correct MEV protection flag
        mock_client_class.assert_called_once()
        call_kwargs = mock_client_class.call_args[1]
        assert call_kwargs['use_mev_protection'] is True


def test_dex_simple_swap_config_has_mev_protection_field():
    """Test that DexSimpleSwapConfig has use_mev_protection field with default False."""
    config = DexSimpleSwapConfig(
        rpc_url="https://bsc-dataseed1.binance.org",
        private_key="0x" + "11" * 32,
        chain_id=56,
        base_symbol="LINK",
        quote_symbol="USDT",
        amount=1.0,
        amount_is_base=False
    )
    
    # Check default value
    assert hasattr(config, 'use_mev_protection')
    assert config.use_mev_protection is False
    
    # Test explicit enable
    config_enabled = DexSimpleSwapConfig(
        rpc_url="https://bsc-dataseed1.binance.org",
        private_key="0x" + "11" * 32,
        chain_id=56,
        base_symbol="LINK",
        quote_symbol="USDT",
        amount=1.0,
        amount_is_base=False,
        use_mev_protection=True
    )
    assert config_enabled.use_mev_protection is True


def test_dex_pure_mm_config_has_mev_protection_field():
    """Test that DexPureMMConfig has use_mev_protection field with default False."""
    config = DexPureMMConfig(
        rpc_url="https://bsc-dataseed1.binance.org",
        private_keys=["0x" + "11" * 32],
        chain_id=56,
        base_symbol="BTCB",
        quote_symbol="USDT",
        upper_percent=0.5,
        lower_percent=0.5,
        levels_each_side=5,
        order_amount=1.0,
        amount_is_base=False,
        refresh_seconds=60.0
    )
    
    assert hasattr(config, 'use_mev_protection')
    assert config.use_mev_protection is False


def test_dex_batch_swap_config_has_mev_protection_field():
    """Test that DexBatchSwapConfig has use_mev_protection field with default False."""
    config = DexBatchSwapConfig(
        rpc_url="https://bsc-dataseed1.binance.org",
        private_keys=["0x" + "11" * 32],
        chain_id=56,
        base_symbol="BTCB",
        quote_symbol="USDT",
        total_amount=10.0,
        min_price=0.09,
        max_price=0.11,
        num_orders=5,
        distribution="uniform",
        amount_is_base=False
    )
    
    assert hasattr(config, 'use_mev_protection')
    assert config.use_mev_protection is False


def test_dex_dca_config_has_mev_protection_field():
    """Test that DexDCAConfig has use_mev_protection field with default False."""
    config = DexDCAConfig(
        rpc_url="https://bsc-dataseed1.binance.org",
        private_keys=["0x" + "11" * 32],
        chain_id=56,
        base_symbol="BTCB",
        quote_symbol="USDT",
        total_amount=10.0,
        amount_is_base=False,
        interval_seconds=60.0,
        num_orders=5,
        distribution="uniform"
    )
    
    assert hasattr(config, 'use_mev_protection')
    assert config.use_mev_protection is False


def test_dex_simple_swap_passes_mev_protection_to_connector():
    """Test that DexSimpleSwap passes MEV protection flag to connector."""
    with patch('strategies.dex_simple_swap.PancakeSwapConnector') as mock_connector_class:
        mock_connector = Mock()
        mock_connector_class.return_value = mock_connector
        
        config = DexSimpleSwapConfig(
            rpc_url="https://bsc-dataseed1.binance.org",
            private_key="0x" + "11" * 32,
            chain_id=56,
            base_symbol="LINK",
            quote_symbol="USDT",
            amount=1.0,
            amount_is_base=False,
            use_mev_protection=True
        )
        
        strategy = DexSimpleSwap(cfg=config)
        
        # Verify connector was created with MEV protection enabled
        mock_connector_class.assert_called_once()
        call_kwargs = mock_connector_class.call_args[1]
        assert call_kwargs['use_mev_protection'] is True


def test_connector_attribute_stores_mev_protection_state():
    """Test that connector stores MEV protection state for inspection."""
    with patch('connectors.dex.pancakeswap.PancakeSwapClient'):
        connector = PancakeSwapConnector(
            rpc_url="https://bsc-dataseed1.binance.org",
            private_key="0x" + "11" * 32,
            chain_id=56,
            use_mev_protection=True
        )
        
        assert hasattr(connector, 'use_mev_protection')
        assert connector.use_mev_protection is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

