import React from 'react';
import { Space, Asset } from '../types';
import { resolveAssetSource } from '../model/assetSource';

export interface ImageSpaceViewProps {
  space: Space;
  asset: Asset | null;
  onUploadImage: (e: React.ChangeEvent<HTMLInputElement>, spaceId: string) => void;
}

export const ImageSpaceView: React.FC<ImageSpaceViewProps> = ({ space, asset, onUploadImage }) => {
  const inputId = `image-upload-${space.id}`;
  const src = resolveAssetSource(asset);

  if (src) {
    return (
      <img
        src={src}
        alt={asset?.filename || 'Image asset'}
        style={{
          maxWidth: '100%',
          maxHeight: '100%',
          objectFit: 'contain',
          display: 'block',
        }}
      />
    );
  }

  return (
    <div style={{ marginTop: '12px', fontStyle: 'italic', color: '#444', fontSize: '14px', lineHeight: '1.4' }}>
      <label
        htmlFor={inputId}
        style={{
          cursor: 'pointer',
          backgroundColor: '#e0e0e0',
          padding: '8px',
          borderRadius: '4px',
          display: 'inline-block',
        }}
      >
        Choose Image
      </label>
      <input
        id={inputId}
        type="file"
        accept="image/*"
        style={{ display: 'none' }}
        onChange={(e) => onUploadImage(e, space.id)}
      />
    </div>
  );
};
