import sql from "./postgres";
import * as fs from "fs";
import * as path from "path";

/**
 * Simple migration runner that executes SQL files at server startup.
 * Tracks applied migrations in a schema_migrations table.
 */
export async function runMigrations() {
  // Skip if DATABASE_URL is not configured
  if (!process.env.DATABASE_URL) {
    console.log("[migrations] DATABASE_URL not set, skipping migrations");
    return;
  }

  console.log("[migrations] Starting migrations...");

  try {
    // Create migrations tracking table if it doesn't exist
    await sql`
      CREATE TABLE IF NOT EXISTS schema_migrations (
        version VARCHAR(255) PRIMARY KEY,
        applied_at TIMESTAMPTZ DEFAULT NOW()
      )
    `;

    // Get already applied migrations
    const applied = await sql<{ version: string }[]>`
      SELECT version FROM schema_migrations ORDER BY version
    `;
    const appliedVersions = new Set(applied.map((m) => m.version));

    // Read migration files from the migrations directory
    const migrationsDir = path.join(process.cwd(), "db", "migrations");

    if (!fs.existsSync(migrationsDir)) {
      console.log("[migrations] No migrations directory found, skipping");
      return;
    }

    const files = fs
      .readdirSync(migrationsDir)
      .filter((f) => f.endsWith(".sql"))
      .sort();

    if (files.length === 0) {
      console.log("[migrations] No migration files found");
      return;
    }

    // Run pending migrations
    let appliedCount = 0;
    for (const file of files) {
      const version = file.replace(".sql", "");

      if (appliedVersions.has(version)) {
        continue;
      }

      console.log(`[migrations] Applying: ${file}`);

      const filePath = path.join(migrationsDir, file);
      const content = fs.readFileSync(filePath, "utf-8");

      // Extract the "up" portion (before -- migrate:down if present)
      const upSql = content
        .split("-- migrate:down")[0]
        .replace("-- migrate:up", "")
        .trim();

      // Run the migration in a transaction for atomicity
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      await sql.begin(async (sql: any) => {
        await sql.unsafe(upSql);
        await sql`INSERT INTO schema_migrations (version) VALUES (${version})`;
      });

      console.log(`[migrations] Applied: ${file}`);
      appliedCount++;
    }

    if (appliedCount > 0) {
      console.log(`[migrations] Successfully applied ${appliedCount} migration(s)`);
    } else {
      console.log("[migrations] No pending migrations");
    }
  } catch (error) {
    console.error("[migrations] Migration failed:", error);
    throw error; // Re-throw to prevent server from starting with broken schema
  }
}
