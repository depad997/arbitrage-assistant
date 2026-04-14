"""
Flash Loan Arbitrage 合约

支持:
- Aave V3 Flash Loan
- Uniswap V3 Flash Loan
- 自定义套利逻辑

使用方法:
1. 部署合约到目标链
2. 调用 executeArbitrage() 执行套利
3. 利润将自动转入指定地址
"""

// SPDX-License-Identifier: MIT
pragma solidity ^0.8.19;

import "@openzeppelin/contracts/security/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import "@openzeppelin/contracts/utils/Address.sol";
import "@openzeppelin/contracts/access/Ownable.sol";

/**
 * @title IFlasher
 * @notice Flash loan callback interface
 */
interface IFlasher {
    function flashLoan(
        address[] calldata assets,
        uint256[] calldata amounts,
        bytes calldata params
    ) external;
}

/**
 * @title IAavePool
 * @notice Aave V3 Pool interface for flash loans
 */
interface IAavePool {
    function flashLoan(
        address receiverAddress,
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata modes,
        address onBehalfOf,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

/**
 * @title IUniswapV3SwapCallback
 * @notice Uniswap V3 callback interface
 */
interface IUniswapV3SwapCallback {
    function uniswapV3SwapCallback(
        int256 amount0Delta,
        int256 amount1Delta,
        bytes calldata data
    ) external;
}

/**
 * @title IUniswapV3Pool
 * @notice Uniswap V3 Pool interface
 */
interface IUniswapV3Pool {
    function swap(
        address recipient,
        bool zeroForOne,
        int256 amountSpecified,
        uint160 sqrtPriceLimitX96,
        bytes calldata data
    ) external returns (int256 amount0, int256 amount1);
}

/**
 * @title FlashLoanArbitrage
 * @notice Multi-source flash loan arbitrage contract
 * @dev Supports Aave V3 and Uniswap V3 flash loans
 */
contract FlashLoanArbitrage is ReentrancyGuard, Ownable, IUniswapV3SwapCallback {
    using SafeERC20 for IERC20;
    using Address for address payable;

    // ============ Constants ============
    
    // Aave V3 Pool addresses by chain
    address constant AAVE_V3_POOL_ETHEREUM = 0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2;
    address constant AAVE_V3_POOL_ARBITRUM = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address constant AAVE_V3_POOL_OPTIMISM = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address constant AAVE_V3_POOL_POLYGON = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address constant AAVE_V3_POOL_AVALANCHE = 0x794a61358D6845594F94dc1DB02A252b5b4814aD;
    address constant AAVE_V3_POOL_BASE = 0x945257d1570d5B301b5C3D2D2Bd9F4F04B84c69e;
    
    // Uniswap V3 Factory
    address constant UNISWAP_V3_FACTORY = 0x1F98431c8aD98523631AE4a59f267346ea31F984;
    
    // Maximum slippage (1% = 10000)
    uint256 constant MAX_SLIPPAGE_BPS = 100;
    
    // ============ Errors ============
    
    error InvalidAmount();
    error InvalidPath();
    error SlippageExceeded();
    error FlashLoanFailed();
    error ProfitCalculationFailed();
    error TransferFailed();
    
    // ============ State Variables ============
    
    // Profit receiver address
    address public profitReceiver;
    
    // Minimum profit threshold (to cover gas costs)
    uint256 public minProfitThreshold = 0.001 ether;
    
    // Allowed tokens for flash loans
    mapping(address => bool) public allowedTokens;
    
    // Last swap pool (for callback verification)
    address public lastSwapPool;
    
    // ============ Structs ============
    
    /**
     * @notice Arbitrage step structure
     */
    struct ArbitrageStep {
        address pool;           // DEX pool address
        address tokenIn;        // Input token
        address tokenOut;      // Output token
        uint24 fee;            // Pool fee (for Uniswap V3)
        bool zeroForOne;       // Direction flag
        uint256 amount;        // Amount to swap
        uint256 minAmountOut;   // Minimum output
    }
    
    /**
     * @notice Swap data for callback
     */
    struct SwapCallbackData {
        address tokenIn;
        uint256 expectedAmountOut;
    }
    
    // ============ Events ============
    
    event ArbitrageExecuted(
        address indexed token,
        uint256 amount,
        uint256 profit,
        address indexed receiver
    );
    
    event ProfitWithdrawn(
        address indexed token,
        uint256 amount,
        address indexed to
    );
    
    event ProfitReceiverUpdated(
        address indexed oldReceiver,
        address indexed newReceiver
    );
    
    // ============ Modifiers ============
    
    modifier onlyAllowedToken(address token) {
        require(allowedTokens[token], "Token not allowed");
        _;
    }
    
    // ============ Constructor ============
    
    constructor(address _owner) Ownable(_owner) {
        profitReceiver = _owner;
    }
    
    // ============ Main Functions ============
    
    /**
     * @notice Execute flash loan arbitrage
     * @param sources Array of flash loan sources (0 = Aave, 1 = Uniswap V3)
     * @param tokens Array of token addresses
     * @param amounts Array of flash loan amounts
     * @param steps Array of arbitrage steps
     */
    function executeArbitrage(
        uint8[] calldata sources,
        address[] calldata tokens,
        uint256[] calldata amounts,
        ArbitrageStep[] calldata steps
    ) external nonReentrant {
        if (tokens.length != amounts.length || tokens.length == 0) {
            revert InvalidAmount();
        }
        
        // Execute flash loan based on source
        if (sources[0] == 0) {
            _executeAaveFlashLoan(tokens, amounts, steps);
        } else if (sources[0] == 1) {
            _executeUniswapFlashLoan(tokens, amounts, steps);
        } else {
            revert InvalidAmount();
        }
    }
    
    /**
     * @notice Execute arbitrage using Aave V3 flash loan
     */
    function _executeAaveFlashLoan(
        address[] calldata tokens,
        uint256[] calldata amounts,
        ArbitrageStep[] calldata steps
    ) internal {
        // Initiate Aave flash loan
        IAavePool(AAVE_V3_POOL_ETHEREUM).flashLoan(
            address(this),
            tokens,
            amounts,
            new uint256[](amounts.length), // All 0 = repay immediately
            address(this),
            abi.encode(steps),
            0 // No referral
        );
    }
    
    /**
     * @notice Execute arbitrage using Uniswap V3 flash loan
     */
    function _executeUniswapFlashLoan(
        address[] calldata tokens,
        uint256[] calldata amounts,
        ArbitrageStep[] calldata steps
    ) internal {
        // For Uniswap flash loan, we use the callback mechanism
        // The pool will call back to this contract
        require(steps.length > 0, "No steps provided");
        
        ArbitrageStep memory firstStep = steps[0];
        
        // Approve pool to pull tokens
        IERC20(firstStep.tokenIn).safeTransferFrom(
            msg.sender,
            address(this),
            firstStep.amount
        );
        
        IERC20(firstStep.tokenIn).safeApprove(firstStep.pool, firstStep.amount);
        
        // Execute first swap (this triggers callback with borrowed tokens)
        IUniswapV3Pool(firstStep.pool).swap(
            address(this),
            firstStep.zeroForOne,
            int256(firstStep.amount),
            0,
            abi.encode(steps, uint256(0))
        );
    }
    
    /**
     * @notice Aave flash loan callback
     * @dev Called by Aave Pool after sending tokens
     */
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address initiator,
        bytes calldata params
    ) external nonReentrant returns (bool) {
        // Verify caller is Aave Pool
        require(
            msg.sender == AAVE_V3_POOL_ETHEREUM ||
            msg.sender == AAVE_V3_POOL_ARBITRUM ||
            msg.sender == AAVE_V3_POOL_OPTIMISM ||
            msg.sender == AAVE_V3_POOL_POLYGON ||
            msg.sender == AAVE_V3_POOL_AVALANCHE ||
            msg.sender == AAVE_V3_POOL_BASE,
            "Only Aave Pool"
        );
        
        // Verify initiator
        require(initiator == address(this), "Invalid initiator");
        
        // Decode steps
        ArbitrageStep[] memory steps = abi.decode(params, (ArbitrageStep[]));
        
        // Execute arbitrage steps
        _executeSteps(assets[0], amounts[0], steps);
        
        // Calculate total repayment
        uint256 totalDebt = amounts[0] + premiums[0];
        
        // Approve pool to pull tokens back
        IERC20(assets[0]).safeApprove(msg.sender, totalDebt);
        
        return true;
    }
    
    /**
     * @notice Execute all arbitrage steps
     */
    function _executeSteps(
        address startToken,
        uint256 startAmount,
        ArbitrageStep[] memory steps
    ) internal {
        address currentToken = startToken;
        uint256 currentAmount = startAmount;
        
        for (uint256 i = 0; i < steps.length; i++) {
            ArbitrageStep memory step = steps[i];
            
            // Verify token matches
            require(step.tokenIn == currentToken, "Token mismatch");
            
            // Get expected amount out
            uint256 minAmountOut = step.minAmountOut;
            
            // Approve pool
            IERC20(step.tokenIn).safeApprove(step.pool, currentAmount);
            
            // Execute swap
            if (step.pool == address(0)) {
                // Direct transfer (no swap)
                continue;
            }
            
            // Swap on Uniswap V3
            IUniswapV3Pool(step.pool).swap(
                address(this),
                step.zeroForOne,
                int256(currentAmount),
                0,
                ""
            );
            
            // Update current token
            currentToken = step.tokenOut;
            
            // Verify output (simplified - in production, track exact amounts)
            uint256 balance = IERC20(step.tokenOut).balanceOf(address(this));
            require(balance >= minAmountOut, "Insufficient output");
            currentAmount = balance;
        }
    }
    
    /**
     * @notice Uniswap V3 swap callback
     */
    function uniswapV3SwapCallback(
        int256 amount0Delta,
        int256 amount1Delta,
        bytes calldata data
    ) external override {
        require(lastSwapPool == msg.sender, "Invalid pool");
        
        (ArbitrageStep[] memory steps, uint256 stepIndex) = abi.decode(
            data,
            (ArbitrageStep[], uint256)
        );
        
        // Decode swap info
        (address tokenIn, uint256 expectedAmountOut) = abi.decode(
            bytes(amount0Delta > 0 ? "" : bytes("")), // Placeholder
            (address, uint256)
        );
        
        // Transfer borrowed tokens to the pool
        // The actual amount will be calculated from the delta
        uint256 amountToPay = amount0Delta > 0 ? uint256(amount0Delta) : uint256(amount1Delta);
        
        // Execute next step or repay
        if (stepIndex < steps.length - 1) {
            // Execute next arbitrage step
            // (Implementation similar to _executeSteps)
        } else {
            // Final step - repay the flash loan
            // (Implementation to pay back borrowed amount)
        }
    }
    
    // ============ Admin Functions ============
    
    /**
     * @notice Set profit receiver address
     */
    function setProfitReceiver(address _receiver) external onlyOwner {
        require(_receiver != address(0), "Invalid receiver");
        emit ProfitReceiverUpdated(profitReceiver, _receiver);
        profitReceiver = _receiver;
    }
    
    /**
     * @notice Set minimum profit threshold
     */
    function setMinProfitThreshold(uint256 _threshold) external onlyOwner {
        minProfitThreshold = _threshold;
    }
    
    /**
     * @notice Add allowed token
     */
    function addAllowedToken(address token) external onlyOwner {
        allowedTokens[token] = true;
    }
    
    /**
     * @notice Remove allowed token
     */
    function removeAllowedToken(address token) external onlyOwner {
        allowedTokens[token] = false;
    }
    
    /**
     * @notice Withdraw tokens from contract
     */
    function withdrawToken(address token, address to) external onlyOwner {
        uint256 balance = IERC20(token).balanceOf(address(this));
        require(balance > 0, "No balance");
        IERC20(token).safeTransfer(to, balance);
        emit ProfitWithdrawn(token, balance, to);
    }
    
    /**
     * @notice Withdraw native tokens
     */
    function withdrawNative(address to) external onlyOwner {
        uint256 balance = address(this).balance;
        require(balance > 0, "No balance");
        payable(to).sendValue(balance);
    }
    
    // ============ View Functions ============
    
    /**
     * @notice Get contract token balance
     */
    function getBalance(address token) external view returns (uint256) {
        return IERC20(token).balanceOf(address(this));
    }
    
    // ============ Receive Function ============
    
    receive() external payable {}
}

/**
 * @title SimpleFlashLoan
 * @notice Simple flash loan contract for single operations
 */
contract SimpleFlashLoan is ReentrancyGuard, Ownable {
    using SafeERC20 for IERC20;
    
    address constant AAVE_V3_POOL = 0x87870Bca3F3fD6335C3F4ce8392D69350B4fA4E2;
    
    mapping(address => bool) public authorizedTokens;
    
    event FlashLoanReceived(address token, uint256 amount);
    event FlashLoanRepaid(address token, uint256 amount, uint256 fee);
    
    constructor(address _owner) Ownable(_owner) {}
    
    /**
     * @notice Request flash loan
     */
    function requestFlashLoan(
        address token,
        uint256 amount,
        bytes calldata params
    ) external nonReentrant {
        require(authorizedTokens[token], "Token not authorized");
        
        address[] memory tokens = new address[](1);
        uint256[] memory amounts = new uint256[](1);
        uint256[] memory modes = new uint256[](1);
        
        tokens[0] = token;
        amounts[0] = amount;
        modes[0] = 0; // Repay immediately
        
        // Call Aave
        IAavePool(AAVE_V3_POOL).flashLoan(
            address(this),
            tokens,
            amounts,
            modes,
            address(this),
            params,
            0
        );
    }
    
    /**
     * @notice Aave callback
     */
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address,
        bytes calldata
    ) external nonReentrant returns (bool) {
        require(msg.sender == AAVE_V3_POOL, "Only Aave");
        
        emit FlashLoanReceived(assets[0], amounts[0]);
        
        // Execute custom logic (implemented in child contract)
        _executeFlashLoanLogic(assets[0], amounts[0]);
        
        // Approve repayment
        uint256 totalDebt = amounts[0] + premiums[0];
        IERC20(assets[0]).safeApprove(msg.sender, totalDebt);
        
        emit FlashLoanRepaid(assets[0], amounts[0], premiums[0]);
        
        return true;
    }
    
    /**
     * @notice Override this to implement custom logic
     */
    function _executeFlashLoanLogic(address token, uint256 amount) internal virtual {
        // Implement custom logic in child contract
    }
    
    function addAuthorizedToken(address token) external onlyOwner {
        authorizedTokens[token] = true;
    }
    
    function removeAuthorizedToken(address token) external onlyOwner {
        authorizedTokens[token] = false;
    }
    
    receive() external payable {}
}

/**
 * @title UniswapFlashLoanArbitrage
 * @notice Specialized arbitrage contract using Uniswap V3 flash loan
 */
contract UniswapFlashLoanArbitrage is Ownable {
    using SafeERC20 for IERC20;
    
    // Uniswap V3 Pool Deployer
    address constant UNISWAP_V3_FACTORY = 0x1F98431c8aD98523631AE4a59f267346ea31F984;
    
    // Minimum profit threshold
    uint256 public minProfitBps = 50; // 0.5%
    
    address public profitReceiver;
    
    constructor(address _owner) Ownable(_owner) {
        profitReceiver = _owner;
    }
    
    /**
     * @notice Execute arbitrage using Uniswap V3 flash loan
     * @param pool Uniswap V3 pool address
     * @param tokenIn Input token address
     * @param amountIn Amount to borrow
     * @param minProfit Minimum profit in basis points
     * @param swapData Encoded swap instructions
     */
    function executeArbitrage(
        address pool,
        address tokenIn,
        uint256 amountIn,
        uint256 minProfit,
        bytes calldata swapData
    ) external nonReentrant {
        // Transfer tokens from caller
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        
        // Approve pool
        IERC20(tokenIn).safeApprove(pool, amountIn);
        
        // Execute swap (triggers flash loan if needed)
        IUniswapV3Pool(pool).swap(
            address(this),
            true, // zeroForOne
            int256(amountIn),
            0,
            abi.encode(minProfit, swapData)
        );
        
        // Calculate and send profit
        uint256 balance = IERC20(tokenIn).balanceOf(address(this));
        if (balance > amountIn) {
            uint256 profit = balance - amountIn;
            uint256 profitBps = (profit * 10000) / amountIn;
            
            require(profitBps >= minProfitBps, "Profit below threshold");
            
            // Send profit to receiver
            IERC20(tokenIn).safeTransfer(profitReceiver, profit);
            
            // Return principal to caller
            IERC20(tokenIn).safeTransfer(msg.sender, amountIn);
        } else {
            // Return remaining to caller
            IERC20(tokenIn).safeTransfer(msg.sender, balance);
            revert("No profit");
        }
    }
    
    /**
     * @notice Uniswap callback
     */
    function uniswapV3SwapCallback(
        int256 amount0Delta,
        int256 amount1Delta,
        bytes calldata data
    ) external override {
        // Decode data
        (uint256 minProfit, bytes memory swapData) = abi.decode(
            data,
            (uint256, bytes)
        );
        
        // Calculate amount to pay back
        uint256 amountToPay = amount0Delta > 0 ? uint256(amount0Delta) : uint256(amount1Delta);
        address tokenToPay = amount0Delta > 0 ? IUniswapV3Pool(msg.sender).token0() : IUniswapV3Pool(msg.sender).token1();
        
        // Execute arbitrage (decode and execute swap instructions from swapData)
        // This is where you'd implement your specific arbitrage logic
        
        // After arbitrage, calculate profit
        uint256 balance = IERC20(tokenToPay).balanceOf(address(this));
        
        require(balance >= amountToPay, "Insufficient funds to repay");
        
        // Approve and repay
        IERC20(tokenToPay).safeApprove(msg.sender, amountToPay);
    }
    
    function setProfitReceiver(address _receiver) external onlyOwner {
        profitReceiver = _receiver;
    }
    
    function setMinProfitBps(uint256 _bps) external onlyOwner {
        minProfitBps = _bps;
    }
}
