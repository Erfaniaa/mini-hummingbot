"""
Tests for MEV protection functionality in PancakeSwap connector.

MEV (Maximal Extractable Value) protection prevents frontrunning and sandwich attacks
by routing transactions through PancakeSwap's private RPC endpoint.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch
from connectors.dex.pancakeswap import PancakeSwapClient, PancakeSwapConnector
from strategies.dex_simple_swap import DexSimpleSwapConfig, DexSimpleSwap
from strategies.dex_pure_market_making import DexPureMMConfig
from strategies.dex_batch_swap import DexBatchSwapConfig
from strategies.dex_dca import DexDCAConfig


def test_mev_protected_rpc_endpoints_exist():
    """Test that MEV protected RPC endpoints are configured for supported chains."""
    assert 56 in PancakeSwapClient.MEV_PROTECTED_RPC
    assert 97 in PancakeSwapClient.MEV_PROTECTED_RPC
    assert PancakeSwapClient.MEV_PROTECTED_RPC[56] == "https://bscrpc.pancakeswap.finance"


def test_pancakeswap_client_uses_mev_protected_rpc_when_enabled():
    """Test that PancakeSwapClient uses MEV protected RPC when flag is enabled."""
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
        
        # Verify the correct RPC was used (MEV protected)
        args, kwargs = mock_web3.HTTPProvider.call_args
        assert args[0] == "https://bscrpc.pancakeswap.finance"


def test_pancakeswap_client_uses_normal_rpc_when_disabled():
    """Test that PancakeSwapClient uses provided RPC when MEV protection is disabled."""
    with patch('connectors.dex.pancakeswap.Web3') as mock_web3:
        mock_web3_instance = Mock()
        mock_web3_instance.is_connected.return_value = True
        mock_web3.return_value = mock_web3_instance
        
        # Create client with MEV protection disabled
        normal_rpc = "https://bsc-dataseed1.binance.org"
        client = PancakeSwapClient(
            rpc_url=normal_rpc,
            private_key="0x" + "11" * 32,
            chain_id=56,
            use_mev_protection=False
        )
        
        # Verify the normal RPC was used
        args, kwargs = mock_web3.HTTPProvider.call_args
        assert args[0] == normal_rpc


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


def test_mev_protection_for_testnet_chain():
    """Test that MEV protection works correctly for testnet (chain 97)."""
    with patch('connectors.dex.pancakeswap.Web3') as mock_web3:
        mock_web3_instance = Mock()
        mock_web3_instance.is_connected.return_value = True
        mock_web3.return_value = mock_web3_instance
        
        # Create client with MEV protection on testnet
        client = PancakeSwapClient(
            rpc_url="https://data-seed-prebsc-1-s1.binance.org:8545",
            private_key="0x" + "11" * 32,
            chain_id=97,
            use_mev_protection=True
        )
        
        # Verify testnet MEV protected RPC was used
        args, kwargs = mock_web3.HTTPProvider.call_args
        assert args[0] == PancakeSwapClient.MEV_PROTECTED_RPC[97]


def test_mev_protection_disabled_uses_provided_rpc():
    """Test that when MEV protection is disabled, the provided RPC is used even for supported chains."""
    with patch('connectors.dex.pancakeswap.Web3') as mock_web3:
        mock_web3_instance = Mock()
        mock_web3_instance.is_connected.return_value = True
        mock_web3.return_value = mock_web3_instance
        
        # Create client with MEV protection disabled on a supported chain
        custom_rpc = "https://custom-bsc-node.example.com"
        client = PancakeSwapClient(
            rpc_url=custom_rpc,
            private_key="0x" + "11" * 32,
            chain_id=56,  # Supported chain
            use_mev_protection=False  # Explicitly disabled
        )
        
        # Verify custom RPC is used when MEV protection is disabled
        args, kwargs = mock_web3.HTTPProvider.call_args
        assert args[0] == custom_rpc
        # Verify we didn't accidentally use the MEV protected RPC
        assert args[0] != PancakeSwapClient.MEV_PROTECTED_RPC[56]


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

