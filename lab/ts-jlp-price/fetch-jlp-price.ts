
import { Connection, PublicKey } from "@solana/web3.js";

const JLP_POOL = "5BUwFW4nRbftYTDMbgxykoFWqWHPzahFSNAaaaJtVKsq";
const JLP_MINT = "27G8MtK7VtTcCHkpASjSDdkWWYfoqT6ggEuKidVJidD4";

async function main() {
    const rpcUrl = process.env.SOLANA_RPC_URL || "https://api.mainnet-beta.solana.com";
    const connection = new Connection(rpcUrl);
    
    // Fetch JLP token supply
    const mintPubkey = new PublicKey(JLP_MINT);
    const supplyInfo = await connection.getTokenSupply(mintPubkey);
    const jlpSupply = parseFloat(supplyInfo.value.uiAmountString || "0");
    
    // Fetch Pool account
    const poolPubkey = new PublicKey(JLP_POOL);
    const poolAccount = await connection.getAccountInfo(poolPubkey);
    
    if (!poolAccount) {
        console.error("Failed to fetch Pool account");
        process.exit(1);
    }
    
    // NOTE: Full implementation would use Jupiter Perpetuals IDL to decode
    // For now, output what we have
    console.log(JSON.stringify({
        jlpSupply,
        poolDataSize: poolAccount.data.length,
        note: "Full IDL parsing not implemented in this minimal example"
    }));
}

main().catch(console.error);
