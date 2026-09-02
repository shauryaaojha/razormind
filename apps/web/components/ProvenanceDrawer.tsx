"use client";

/**
 * Where a number comes from, all the way down.
 *
 * One recursive renderer with no knowledge of revenue, refunds or
 * reconciliation. Every level of a chain is an evidence node that either
 * declares a formula — in which case its operands are more nodes — or declares
 * a fold, in which case it cites records and the walk stops. A component per
 * metric would have to be written again for every metric anyone adds, and the
 * one nobody wrote would be the one that silently showed nothing.
 *
 * The whole chain arrives in a single request. The original design lazy-loaded
 * level by level, which cannot answer the question the drawer exists for: "is
 * this chain intact?" is not answerable until the last request returns.
 */

import {
  Alert,
  Badge,
  Box,
  Divider,
  Drawer,
  DrawerBody,
  DrawerHeader,
  Heading,
  Spinner,
  Text,
} from "@razorpay/blade/components";
import type { EvidenceDetail, ProvenanceLevel } from "@shared/api";
import { useEffect, useState } from "react";

import { readEvidence } from "@/lib/api";

export function ProvenanceDrawer({
  executionId,
  evidenceId,
  onDismiss,
}: {
  executionId: string;
  evidenceId: string | null;
  onDismiss: () => void;
}) {
  const [detail, setDetail] = useState<EvidenceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!evidenceId) return;
    let live = true;
    setDetail(null);
    setError(null);
    readEvidence(executionId, evidenceId)
      .then((loaded) => live && setDetail(loaded))
      .catch((failure: Error) => live && setError(failure.message));
    return () => {
      live = false;
    };
  }, [executionId, evidenceId]);

  return (
    <Drawer isOpen={evidenceId !== null} onDismiss={onDismiss}>
      <DrawerHeader title="Where this number comes from" subtitle={evidenceId ?? ""} />
      <DrawerBody>
        {error ? (
          <Alert isFullWidth color="negative" title="Cannot show this" description={error} />
        ) : !detail ? (
          <Spinner accessibilityLabel="Loading the evidence chain" size="medium" />
        ) : (
          <Box display="flex" flexDirection="column" gap="spacing.5">
            <Level node={detail.provenance} depth={0} />
            <Divider />
            <Box display="flex" flexDirection="column" gap="spacing.2">
              <Text weight="semibold" size="small">
                {detail.source_record_ids.length.toLocaleString("en-IN")} source records
              </Text>
              <Text size="xsmall" color="surface.text.gray.muted">
                Every record the whole chain reaches, however deep. This is the answer to
                &ldquo;show me the transactions behind this percentage&rdquo;.
              </Text>
              <Box display="flex" flexWrap="wrap" gap="spacing.2" testID="source-records">
                {detail.source_record_ids.slice(0, 60).map((record) => (
                  <Badge key={record} color="neutral" size="small">
                    {record}
                  </Badge>
                ))}
                {detail.source_record_ids.length > 60 ? (
                  <Text size="xsmall" color="surface.text.gray.muted">
                    + {detail.source_record_ids.length - 60} more
                  </Text>
                ) : null}
              </Box>
            </Box>
          </Box>
        )}
      </DrawerBody>
    </Drawer>
  );
}

/** One node, then its operands, then theirs. The whole renderer. */
export function Level({ node, depth }: { node: ProvenanceLevel; depth: number }) {
  return (
    <Box
      display="flex"
      flexDirection="column"
      gap="spacing.2"
      paddingLeft={depth === 0 ? "spacing.0" : "spacing.5"}
      testID="provenance-node"
    >
      <Box display="flex" alignItems="center" gap="spacing.3" flexWrap="wrap">
        <Text weight="semibold">{node.display}</Text>
        <Text size="small" color="surface.text.gray.muted">
          {node.metric_id}
          {node.dimension_value ? ` · ${node.dimension_value}` : ""}
        </Text>
        <Badge color={node.support === "FORMULA" ? "information" : "neutral"} size="small">
          {node.support === "FORMULA" ? "derived" : "fold"}
        </Badge>
      </Box>

      <Text size="xsmall" color="surface.text.gray.muted">
        {node.detail}
      </Text>
      <Text size="xsmall" color="surface.text.gray.muted">
        {node.tool_name} · [{node.period_from}, {node.period_to})
      </Text>

      {node.operands.map((operand) => (
        <Box key={`${operand.name}:${operand.reference}`} display="flex" flexDirection="column">
          <Text size="xsmall" color="surface.text.gray.muted">
            {operand.name} = {operand.display}
          </Text>
          {operand.node ? <Level node={operand.node} depth={depth + 1} /> : null}
        </Box>
      ))}

      {node.support === "AGGREGATION" && node.source_record_ids.length > 0 ? (
        <Text size="xsmall" color="surface.text.gray.muted">
          folds {node.source_record_ids.length.toLocaleString("en-IN")} records
        </Text>
      ) : null}
    </Box>
  );
}
