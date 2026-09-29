export function resetSpaceRotationMatrix(matrix?: number[] | null): number[] {
  const e = matrix && typeof matrix[4] === 'number' ? matrix[4] : 0;
  const f = matrix && typeof matrix[5] === 'number' ? matrix[5] : 0;
  return [1, 0, 0, 1, e, f];
}
