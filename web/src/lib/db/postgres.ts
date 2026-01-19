import postgres from "postgres";

// PostgreSQL connection singleton
// Returns null if DATABASE_URL is not configured
let sql: ReturnType<typeof postgres> | null = null;

if (process.env.DATABASE_URL) {
  try {
    sql = postgres(process.env.DATABASE_URL, {
      max: 10, // Connection pool size
      idle_timeout: 30,
      connect_timeout: 10,
      onnotice: () => {}, // Suppress PostgreSQL NOTICE messages
    });
  } catch (error) {
    console.warn("[database] Failed to create PostgreSQL connection:", error);
  }
} else {
  console.warn(
    "[database] DATABASE_URL not set - database features will be disabled"
  );
}

/**
 * Gracefully close the database connection pool
 */
async function closeDatabase(): Promise<void> {
  if (sql) {
    console.log("[database] Closing connection pool...");
    await sql.end({ timeout: 5 });
    console.log("[database] Connection pool closed");
  }
}

// Register shutdown handlers for graceful cleanup
const shutdownHandler = async () => {
  await closeDatabase();
  process.exit(0);
};

process.on("SIGTERM", shutdownHandler);
process.on("SIGINT", shutdownHandler);

export default sql;
