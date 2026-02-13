import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  formatRelativeTime,
  formatTimestamp,
  formatTokenCount,
  formatDate,
} from './formatters';

describe('Formatters', () => {
  beforeEach(() => {
    // Set a fixed date for consistent testing
    vi.setSystemTime(new Date('2024-01-01T12:00:00Z'));
  });

  describe('formatRelativeTime', () => {
    it('shows "just now" for recent times', () => {
      const date = new Date('2024-01-01T11:59:50Z');
      expect(formatRelativeTime(date)).toBe('just now');
    });

    it('shows minutes for times under 1 hour', () => {
      const date = new Date('2024-01-01T11:30:00Z');
      expect(formatRelativeTime(date)).toBe('30m ago');
    });

    it('shows hours for times under 24 hours', () => {
      const date = new Date('2024-01-01T08:00:00Z');
      expect(formatRelativeTime(date)).toBe('4h ago');
    });

    it('shows days for times under 7 days', () => {
      const date = new Date('2023-12-30T12:00:00Z');
      expect(formatRelativeTime(date)).toBe('2d ago');
    });

    it('shows date for times over 7 days', () => {
      const date = new Date('2023-12-20T12:00:00Z');
      expect(formatRelativeTime(date)).toContain('12/20');
    });

    it('handles string dates', () => {
      const result = formatRelativeTime('2024-01-01T11:30:00Z');
      expect(result).toBe('30m ago');
    });
  });

  describe('formatTimestamp', () => {
    it('formats time correctly', () => {
      const date = new Date('2024-01-01T14:30:00Z');
      const result = formatTimestamp(date);
      // Result depends on locale, just check it's a string
      expect(typeof result).toBe('string');
      expect(result.length).toBeGreaterThan(0);
    });

    it('handles string dates', () => {
      const result = formatTimestamp('2024-01-01T14:30:00Z');
      expect(typeof result).toBe('string');
    });
  });

  describe('formatTokenCount', () => {
    it('shows raw number for counts under 1000', () => {
      expect(formatTokenCount(500)).toBe('500');
      expect(formatTokenCount(999)).toBe('999');
    });

    it('shows K notation for counts over 1000', () => {
      expect(formatTokenCount(1000)).toBe('1.0k');
      expect(formatTokenCount(1500)).toBe('1.5k');
      expect(formatTokenCount(12345)).toBe('12.3k');
    });

    it('handles null and undefined', () => {
      expect(formatTokenCount(null)).toBe('');
      expect(formatTokenCount(undefined)).toBe('');
    });

    it('handles zero', () => {
      expect(formatTokenCount(0)).toBe('0');
    });
  });

  describe('formatDate', () => {
    it('formats date with month, day, and time', () => {
      const date = new Date('2024-06-15T14:30:00Z');
      const result = formatDate(date);
      expect(result).toContain('Jun');
      expect(result).toContain('15');
    });

    it('handles string dates', () => {
      const result = formatDate('2024-06-15T14:30:00Z');
      expect(typeof result).toBe('string');
      expect(result.length).toBeGreaterThan(0);
    });
  });
});
