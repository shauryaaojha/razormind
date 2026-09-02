"use client";

/** Every investigation this merchant has run, newest first. */

import {
  Alert,
  Badge,
  Box,
  Card,
  CardBody,
  EmptyState,
  Link,
  Spinner,
  Text,
} from "@razorpay/blade/components";
import type { ExecutionLine } from "@shared/api";
import { useEffect, useState } from "react";

import { Shell } from "@/components/Shell";
import { listExecutions } from "@/lib/api";

const COLOUR: Record<string, "positive" | "negative" | "notice" | "neutral"> = {
  COMPLETED: "positive",
  BLOCKED: "negative",
  FAILED: "negative",
  REJECTED: "negative",
  NEEDS_CLARIFICATION: "notice",
};

export default function HistoryPage() {
  const [items, setItems] = useState<ExecutionLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    listExecutions(50)
      .then((page) => live && setItems(page.items))
      .catch((failure: Error) => live && setError(failure.message));
    return () => {
      live = false;
    };
  }, []);

  return (
    <Shell
      title="History"
      subtitle="Every run is replayable through the same trace the chat page shows live."
    >
      {error ? (
        <Alert isFullWidth color="negative" title="Cannot list runs" description={error} />
      ) : null}
      {!items ? (
        <Spinner accessibilityLabel="Loading history" size="medium" />
      ) : items.length === 0 ? (
        <EmptyState title="Nothing yet" description="Ask a question and it will appear here." />
      ) : (
        <Box display="flex" flexDirection="column" gap="spacing.3">
          {items.map((item) => (
            <Card key={item.execution_id} padding="spacing.4" elevation="lowRaised">
              <CardBody>
                <Box display="flex" flexDirection="column" gap="spacing.2">
                  <Box display="flex" alignItems="center" gap="spacing.3" flexWrap="wrap">
                    <Badge color={COLOUR[item.status] ?? "neutral"}>{item.status}</Badge>
                    {item.response_source ? (
                      <Badge color="neutral" size="small">
                        {item.response_source === "LLM" ? "model" : "template"}
                      </Badge>
                    ) : null}
                    <Text size="small" color="surface.text.gray.muted">
                      {item.created_at.slice(0, 19).replace("T", " ")}
                    </Text>
                  </Box>
                  <Link href={`/history/${item.execution_id}`}>{item.question}</Link>
                  {item.period_from ? (
                    <Text size="xsmall" color="surface.text.gray.muted">
                      [{item.period_from}, {item.period_to})
                    </Text>
                  ) : null}
                </Box>
              </CardBody>
            </Card>
          ))}
        </Box>
      )}
    </Shell>
  );
}
